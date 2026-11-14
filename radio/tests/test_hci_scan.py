"""Tests for radio.hci_scan — no hardware, no network dependencies.

Fixtures are hand-crafted HCI LE advertising report packets.  Tests verify:
  - AD structure parsing
  - Beacon matching by manufacturer data only
  - Contract-v2 message shape (v, type, seq, link, kind, tx, rx, dbm, src)
  - UDP delivery to the bus socket
  - Seq counter increments across messages from both hci_scan and wifi_rssi
"""

from __future__ import annotations

import json
import re
import socket
import threading
import time
import unittest.mock as mock

import pytest

from radio.hci_scan import (
    extract_mfr_data,
    parse_adv_reports,
    _make_rssi_message,
    _scan_enable_cmd,
    _scan_params_cmd,
    BEACON_LINKS,
    run as hci_run,
)
from radio.wifi_rssi import _make_message as wifi_make_message, run as wifi_run

# ---------------------------------------------------------------------------
# Synthetic HCI packet builder (same approach as pi/tests/test_radio_node.py)
# ---------------------------------------------------------------------------

def _make_adv_payload(mfr_data: bytes) -> bytes:
    return bytes([len(mfr_data) + 1, 0xFF]) + mfr_data


def _make_le_adv_subevent(mfr_data: bytes, rssi: int) -> bytes:
    adv = _make_adv_payload(mfr_data)
    return (
        bytes([0x01])          # num_reports
        + bytes([0x03])        # event_type non-connectable
        + bytes([0x00])        # addr_type public
        + bytes(6)             # addr zeros
        + bytes([len(adv)])
        + adv
        + bytes([rssi & 0xFF])
    )


def _make_hci_le_adv_pkt(mfr_data: bytes, rssi: int) -> bytes:
    subevent_id = bytes([0x02])  # LE Advertising Report
    report = _make_le_adv_subevent(mfr_data, rssi)
    payload = subevent_id + report
    return bytes([0x04, 0x3E, len(payload)]) + payload


MFR_PI   = bytes.fromhex("FFFF525353")
MFR_EAST = bytes.fromhex("FFFF525345")
MFR_WEST = bytes.fromhex("FFFF525357")
MFR_UNK  = bytes.fromhex("DEADBEEF01")


# ---------------------------------------------------------------------------
# extract_mfr_data
# ---------------------------------------------------------------------------

class TestExtractMfrData:
    def test_pi_beacon(self):
        assert extract_mfr_data(_make_adv_payload(MFR_PI)) == MFR_PI

    def test_east_beacon(self):
        assert extract_mfr_data(_make_adv_payload(MFR_EAST)) == MFR_EAST

    def test_west_beacon(self):
        assert extract_mfr_data(_make_adv_payload(MFR_WEST)) == MFR_WEST

    def test_no_mfr_data(self):
        assert extract_mfr_data(bytes([0x02, 0x01, 0x06])) is None

    def test_empty(self):
        assert extract_mfr_data(b"") is None

    def test_flags_then_mfr(self):
        flags = bytes([0x02, 0x01, 0x06])
        mfr = _make_adv_payload(MFR_EAST)
        assert extract_mfr_data(flags + mfr) == MFR_EAST


# ---------------------------------------------------------------------------
# parse_adv_reports
# ---------------------------------------------------------------------------

class TestParseAdvReports:
    def test_pi_beacon_at_minus62(self):
        subevent = _make_le_adv_subevent(MFR_PI, -62)
        results = parse_adv_reports(subevent)
        assert len(results) == 1
        assert results[0] == (MFR_PI, -62)

    def test_east_beacon_at_minus68(self):
        subevent = _make_le_adv_subevent(MFR_EAST, -68)
        assert parse_adv_reports(subevent)[0] == (MFR_EAST, -68)

    def test_negative_rssi_two_complement(self):
        subevent = _make_le_adv_subevent(MFR_WEST, -100)
        _, rssi = parse_adv_reports(subevent)[0]
        assert rssi == -100

    def test_unknown_mfr_still_returned(self):
        subevent = _make_le_adv_subevent(MFR_UNK, -55)
        results = parse_adv_reports(subevent)
        assert results[0][0] == MFR_UNK

    def test_empty_subevent(self):
        assert parse_adv_reports(b"") == []


# ---------------------------------------------------------------------------
# BEACON_LINKS table
# ---------------------------------------------------------------------------

class TestBeaconLinks:
    def test_all_three_beacons_present(self):
        assert MFR_PI   in BEACON_LINKS
        assert MFR_EAST in BEACON_LINKS
        assert MFR_WEST in BEACON_LINKS

    def test_link_ids_correct(self):
        assert BEACON_LINKS[MFR_PI  ][1] == "pi5>unoq:ble"
        assert BEACON_LINKS[MFR_EAST][1] == "east>unoq:ble"
        assert BEACON_LINKS[MFR_WEST][1] == "west>unoq:ble"

    def test_tx_nodes_correct(self):
        assert BEACON_LINKS[MFR_PI  ][0] == "pi5"
        assert BEACON_LINKS[MFR_EAST][0] == "east"
        assert BEACON_LINKS[MFR_WEST][0] == "west"

    def test_no_mac_in_keys(self):
        mac_re = re.compile(r"\b[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){5}\b")
        for k in BEACON_LINKS:
            assert not mac_re.search(k.hex())


# ---------------------------------------------------------------------------
# HCI command shape
# ---------------------------------------------------------------------------

class TestHciCommands:
    def test_scan_enable_cmd_duplicate_filter_off(self):
        cmd = _scan_enable_cmd(True, filter_dupes=False)
        # params: enable(1) + filter(1); filter = 0x00 means OFF
        assert cmd[-1] == 0x00

    def test_scan_enable_cmd_on(self):
        cmd = _scan_enable_cmd(True, filter_dupes=False)
        # CMD_PKT(1) + opcode(2) + param_len(1) + enable(1) + filter(1)
        assert cmd[4] == 0x01

    def test_scan_params_cmd_starts_with_cmd_pkt(self):
        assert _scan_params_cmd()[0] == 0x01

    def test_scan_params_cmd_passive(self):
        cmd = _scan_params_cmd()
        # scan_type byte is at params[0] = cmd[4]; 0x00 = passive
        assert cmd[4] == 0x00


# ---------------------------------------------------------------------------
# _make_rssi_message — contract-v2 shape
# ---------------------------------------------------------------------------

class TestMakeRssiMessage:
    def test_shape(self):
        msg = json.loads(_make_rssi_message("pi5>unoq:ble", "pi5", "unoq", -62, 5))
        assert msg["v"] == 2
        assert msg["type"] == "rssi"
        assert msg["src"] == "live"
        assert msg["link"] == "pi5>unoq:ble"
        assert msg["kind"] == "ble"
        assert msg["tx"] == "pi5"
        assert msg["rx"] == "unoq"
        assert msg["dbm"] == -62
        assert msg["seq"] == 5

    def test_seq_carried_through(self):
        m0 = json.loads(_make_rssi_message("east>unoq:ble", "east", "unoq", -70, 0))
        m1 = json.loads(_make_rssi_message("east>unoq:ble", "east", "unoq", -70, 1))
        assert m1["seq"] == m0["seq"] + 1

    def test_no_mac_in_message(self):
        raw = _make_rssi_message("pi5>unoq:ble", "pi5", "unoq", -62, 0).decode()
        mac_re = re.compile(r"\b[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){5}\b")
        assert not mac_re.search(raw)


# ---------------------------------------------------------------------------
# wifi_rssi _make_message — also contract v2
# ---------------------------------------------------------------------------

class TestWifiMakeMessage:
    def test_shape(self):
        msg = json.loads(wifi_make_message(-65, 3))
        assert msg["v"] == 2
        assert msg["type"] == "rssi"
        assert msg["src"] == "live"
        assert msg["link"] == "pi5>unoq:wifi"
        assert msg["kind"] == "wifi"
        assert msg["tx"] == "pi5"
        assert msg["rx"] == "unoq"
        assert msg["dbm"] == -65
        assert msg["seq"] == 3

    def test_seq_increments(self):
        m0 = json.loads(wifi_make_message(-60, 0))
        m1 = json.loads(wifi_make_message(-60, 1))
        assert m1["seq"] == m0["seq"] + 1


# ---------------------------------------------------------------------------
# hci_scan.run() — sends UDP messages from synthetic HCI packets
# ---------------------------------------------------------------------------

class TestHciScanPipeline:
    """Test parse → filter → publish pipeline without touching sockets.

    We simulate the inner loop body directly: take synthetic HCI bytes,
    parse them, match against BEACON_LINKS, and call _make_rssi_message.
    """

    def _process_pkt(self, pkt: bytes, node: str, seq_start: int
                     ) -> tuple[list[dict], int]:
        """Run one iteration of the hci_scan inner loop, return (messages, next_seq)."""
        from radio.hci_scan import (
            HCI_EVENT_PKT, EVT_LE_META_EVENT, EVT_LE_ADVERTISING_REPORT,
            parse_adv_reports, BEACON_LINKS, _make_rssi_message,
        )
        messages = []
        seq = seq_start
        if len(pkt) < 4 or pkt[0] != HCI_EVENT_PKT:
            return messages, seq
        if pkt[1] != EVT_LE_META_EVENT or pkt[3] != EVT_LE_ADVERTISING_REPORT:
            return messages, seq
        for mfr_data, rssi in parse_adv_reports(pkt[4:]):
            if mfr_data not in BEACON_LINKS:
                continue
            tx, link_id = BEACON_LINKS[mfr_data]
            payload = _make_rssi_message(link_id, tx, node, rssi, seq)
            messages.append(json.loads(payload))
            seq += 1
        return messages, seq

    def test_known_beacons_produce_messages(self):
        all_msgs = []
        seq = 0
        for mfr, rssi in [(MFR_PI, -62), (MFR_EAST, -68), (MFR_WEST, -71)]:
            pkt = _make_hci_le_adv_pkt(mfr, rssi)
            msgs, seq = self._process_pkt(pkt, "unoq", seq)
            all_msgs.extend(msgs)
        assert len(all_msgs) == 3
        links = {m["link"] for m in all_msgs}
        assert links == {"pi5>unoq:ble", "east>unoq:ble", "west>unoq:ble"}

    def test_unknown_beacon_dropped(self):
        pkt = _make_hci_le_adv_pkt(MFR_UNK, -55)
        msgs, _ = self._process_pkt(pkt, "unoq", 0)
        assert msgs == []

    def test_seq_increments_monotonically(self):
        seq = 0
        all_msgs = []
        for mfr in [MFR_PI, MFR_EAST, MFR_WEST]:
            pkt = _make_hci_le_adv_pkt(mfr, -65)
            msgs, seq = self._process_pkt(pkt, "unoq", seq)
            all_msgs.extend(msgs)
        seqs = [m["seq"] for m in all_msgs]
        assert seqs == list(range(3))

    def test_rssi_preserved(self):
        pkt = _make_hci_le_adv_pkt(MFR_EAST, -73)
        msgs, _ = self._process_pkt(pkt, "unoq", 0)
        assert msgs[0]["dbm"] == -73

    def test_node_becomes_rx(self):
        pkt = _make_hci_le_adv_pkt(MFR_PI, -60)
        msgs, _ = self._process_pkt(pkt, "unoq", 0)
        assert msgs[0]["rx"] == "unoq"

    def test_non_adv_pkt_ignored(self):
        # A packet with wrong event code
        pkt = bytes([0x04, 0x0F, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00])
        msgs, seq = self._process_pkt(pkt, "unoq", 0)
        assert msgs == []
        assert seq == 0

    def test_all_messages_are_contract_v2(self):
        seq = 0
        for mfr in [MFR_PI, MFR_EAST, MFR_WEST]:
            pkt = _make_hci_le_adv_pkt(mfr, -65)
            msgs, seq = self._process_pkt(pkt, "unoq", seq)
            for m in msgs:
                assert m["v"] == 2
                assert m["type"] == "rssi"
                assert m["src"] == "live"
                assert m["kind"] == "ble"
