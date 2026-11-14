"""Tests for pi.radio_node — no hardware needed.

Fixtures are hand-crafted HCI packet bytes that mirror real LE advertising
reports.  The tests verify parsing, beacon matching, message shape and UDP
delivery without opening any Bluetooth socket.
"""

from __future__ import annotations

import json
import socket
import struct
import threading
import time
import unittest.mock as mock
from pathlib import Path

import pytest

from pi.radio_node import (
    _extract_mfr_data,
    _parse_adv_report,
    _build_adv_data_cmd,
    _build_scan_enable_cmd,
    _Publisher,
    BEACON_PAYLOADS,
    PI_RX_LINKS,
)


# ---------------------------------------------------------------------------
# Helpers to build synthetic HCI LE advertising report packets
# ---------------------------------------------------------------------------

def _make_adv_payload(mfr_data: bytes) -> bytes:
    """Wrap manufacturer data in a minimal AD structure."""
    # AD length = 1 (type) + len(mfr_data); type = 0xFF
    ad = bytes([len(mfr_data) + 1, 0xFF]) + mfr_data
    return ad


def _make_le_adv_report_subevent(mfr_data: bytes, rssi: int) -> bytes:
    """
    Build a LE Advertising Report subevent payload:
      num_reports(1) event_type(1) addr_type(1) addr(6) data_len(1) data(*) rssi(1)
    """
    adv_payload = _make_adv_payload(mfr_data)
    rssi_byte = rssi & 0xFF  # two's complement to unsigned
    report = (
        bytes([0x01])          # num_reports = 1
        + bytes([0x03])        # event_type: non-connectable undirected
        + bytes([0x00])        # addr_type: public
        + bytes(6)             # addr: 6 zero bytes
        + bytes([len(adv_payload)])
        + adv_payload
        + bytes([rssi_byte])
    )
    return report


def _make_hci_le_adv_event(mfr_data: bytes, rssi: int) -> bytes:
    """
    Build a full HCI event packet:
      packet_type(1) event_code(1) param_len(1) subevent(1) report(*)
    """
    subevent_id = bytes([0x02])  # LE Advertising Report
    report = _make_le_adv_report_subevent(mfr_data, rssi)
    payload = subevent_id + report
    return bytes([0x04, 0x3E, len(payload)]) + payload


# Known beacon mfr_data values (company_id + RS + letter)
MFR_EAST = bytes.fromhex("FFFF525345")
MFR_WEST = bytes.fromhex("FFFF525357")
MFR_PI   = bytes.fromhex("FFFF525353")
MFR_OTHER = bytes.fromhex("ABCD010203")


# ---------------------------------------------------------------------------
# _extract_mfr_data
# ---------------------------------------------------------------------------

class TestExtractMfrData:
    def test_extracts_from_single_ad(self):
        payload = _make_adv_payload(MFR_EAST)
        result = _extract_mfr_data(payload)
        assert result == MFR_EAST

    def test_extracts_from_multi_ad(self):
        # Prepend a flags AD structure before the manufacturer data
        flags = bytes([0x02, 0x01, 0x06])
        payload = flags + _make_adv_payload(MFR_WEST)
        result = _extract_mfr_data(payload)
        assert result == MFR_WEST

    def test_returns_none_when_no_mfr_data(self):
        flags = bytes([0x02, 0x01, 0x06])
        assert _extract_mfr_data(flags) is None

    def test_returns_none_on_empty(self):
        assert _extract_mfr_data(b"") is None

    def test_returns_none_on_truncated(self):
        # length byte says 10 but payload is 2 bytes
        assert _extract_mfr_data(bytes([10, 0xFF, 0xAB])) is None


# ---------------------------------------------------------------------------
# _parse_adv_report
# ---------------------------------------------------------------------------

class TestParseAdvReport:
    def test_parses_east_beacon(self):
        subevent = _make_le_adv_report_subevent(MFR_EAST, -65)
        results = _parse_adv_report(subevent)
        assert len(results) == 1
        mfr, rssi = results[0]
        assert mfr == MFR_EAST
        assert rssi == -65

    def test_parses_west_beacon(self):
        subevent = _make_le_adv_report_subevent(MFR_WEST, -72)
        results = _parse_adv_report(subevent)
        assert len(results) == 1
        assert results[0][0] == MFR_WEST
        assert results[0][1] == -72

    def test_parses_negative_rssi_correctly(self):
        # rssi = -100 → stored as 256 - 100 = 156
        subevent = _make_le_adv_report_subevent(MFR_EAST, -100)
        results = _parse_adv_report(subevent)
        assert results[0][1] == -100

    def test_unrecognised_mfr_still_parsed(self):
        subevent = _make_le_adv_report_subevent(MFR_OTHER, -50)
        results = _parse_adv_report(subevent)
        assert len(results) == 1
        assert results[0][0] == MFR_OTHER

    def test_empty_payload(self):
        assert _parse_adv_report(b"") == []


# ---------------------------------------------------------------------------
# Beacon payload tables
# ---------------------------------------------------------------------------

class TestBeaconTables:
    def test_all_three_beacons_in_payloads(self):
        assert MFR_PI  in BEACON_PAYLOADS
        assert MFR_EAST in BEACON_PAYLOADS
        assert MFR_WEST in BEACON_PAYLOADS

    def test_pi_rx_links_has_east_and_west(self):
        assert MFR_EAST in PI_RX_LINKS
        assert MFR_WEST in PI_RX_LINKS
        # Pi does not hear its own beacon
        assert MFR_PI not in PI_RX_LINKS

    def test_link_ids_match_contract(self):
        _, _, lid_east = PI_RX_LINKS[MFR_EAST]
        _, _, lid_west = PI_RX_LINKS[MFR_WEST]
        assert lid_east == "east>pi5:ble"
        assert lid_west == "west>pi5:ble"

    def test_no_mac_in_payload_keys(self):
        import re
        mac_re = re.compile(r"\b[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){5}\b")
        for key in {**BEACON_PAYLOADS, **PI_RX_LINKS}:
            assert not mac_re.search(key.hex())


# ---------------------------------------------------------------------------
# HCI command builders
# ---------------------------------------------------------------------------

class TestHciCommands:
    def test_adv_data_cmd_starts_with_cmd_pkt(self):
        cmd = _build_adv_data_cmd()
        assert cmd[0] == 0x01  # CMD_PKT

    def test_adv_data_cmd_contains_mfr_payload(self):
        cmd = _build_adv_data_cmd()
        assert bytes.fromhex("FFFF525353") in cmd

    def test_scan_enable_cmd_duplicate_filter_off(self):
        cmd = _build_scan_enable_cmd(True, filter_dupes=False)
        # Last byte of params should be 0x00 (filter duplicates OFF)
        assert cmd[-1] == 0x00

    def test_scan_enable_cmd_enable_byte(self):
        cmd_on  = _build_scan_enable_cmd(True,  filter_dupes=False)
        cmd_off = _build_scan_enable_cmd(False, filter_dupes=False)
        # params start after CMD_PKT(1) + opcode(2) + param_len(1) = offset 4
        assert cmd_on[4]  == 0x01
        assert cmd_off[4] == 0x00


# ---------------------------------------------------------------------------
# _Publisher — sends UDP messages correctly
# ---------------------------------------------------------------------------

class TestPublisher:
    def test_sends_valid_rssi_message(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        sock.settimeout(0.5)
        port = sock.getsockname()[1]

        pub = _Publisher("127.0.0.1", port)
        pub.publish("east>pi5:ble", "east", "pi5", -65)

        data, _ = sock.recvfrom(4096)
        sock.close()
        msg = json.loads(data)
        assert msg["v"] == 2
        assert msg["type"] == "rssi"
        assert msg["link"] == "east>pi5:ble"
        assert msg["tx"] == "east"
        assert msg["rx"] == "pi5"
        assert msg["dbm"] == -65
        assert msg["kind"] == "ble"
        assert msg["src"] == "live"
        assert msg["seq"] == 0

    def test_seq_increments_on_each_send(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        sock.settimeout(0.5)
        port = sock.getsockname()[1]

        pub = _Publisher("127.0.0.1", port)
        pub.publish("east>pi5:ble", "east", "pi5", -65)
        pub.publish("west>pi5:ble", "west", "pi5", -70)

        m1 = json.loads(sock.recvfrom(4096)[0])
        m2 = json.loads(sock.recvfrom(4096)[0])
        sock.close()
        assert m2["seq"] == m1["seq"] + 1

    def test_no_mac_in_message(self):
        import re
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        sock.settimeout(0.5)
        port = sock.getsockname()[1]

        pub = _Publisher("127.0.0.1", port)
        pub.publish("east>pi5:ble", "east", "pi5", -65)

        data, _ = sock.recvfrom(4096)
        sock.close()
        mac_re = re.compile(r"\b[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){5}\b")
        assert not mac_re.search(data.decode())


# ---------------------------------------------------------------------------
# Full packet round-trip: HCI packet → parse → publish
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_east_beacon_round_trip(self):
        """Synthetic HCI packet for east beacon should produce east>pi5:ble message."""
        pkt = _make_hci_le_adv_event(MFR_EAST, -68)

        # Parse the subevent (skip HCI header: pkt_type, event_code, param_len)
        # subevent_code is pkt[3]; report starts at pkt[4]
        assert pkt[1] == 0x3E           # EVT_LE_META_EVENT
        assert pkt[3] == 0x02           # LE_ADVERTISING_REPORT
        reports = _parse_adv_report(pkt[4:])

        assert len(reports) == 1
        mfr_data, rssi = reports[0]
        assert mfr_data == MFR_EAST
        assert rssi == -68
        assert mfr_data in PI_RX_LINKS
        tx, rx, link_id = PI_RX_LINKS[mfr_data]
        assert link_id == "east>pi5:ble"

    def test_west_beacon_round_trip(self):
        pkt = _make_hci_le_adv_event(MFR_WEST, -71)
        reports = _parse_adv_report(pkt[4:])
        mfr_data, rssi = reports[0]
        assert mfr_data == MFR_WEST
        assert rssi == -71
        tx, rx, link_id = PI_RX_LINKS[mfr_data]
        assert link_id == "west>pi5:ble"

    def test_unknown_beacon_not_in_pi_rx_links(self):
        pkt = _make_hci_le_adv_event(MFR_OTHER, -60)
        reports = _parse_adv_report(pkt[4:])
        mfr_data, _ = reports[0]
        assert mfr_data not in PI_RX_LINKS
