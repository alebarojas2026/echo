"""Tests for radio.wifi_rssi and radio.report_wifi.

All tests use recorded fixture text — no hardware, no network.
No MAC-shaped text or device identifiers in this file.
"""

from __future__ import annotations

import json
import re
import socket
import threading
import time
import unittest.mock as mock
from pathlib import Path

import pytest

from radio.wifi_rssi import (
    _make_message,
    _read_station_info,
    parse_station_output,
    _SIGNAL_RE,
    _RX_PACKETS_RE,
    run,
)
from radio.report_wifi import parse_gate_md, check

FIXTURE_DIR = Path(__file__).parent / "fixtures"
CLEAR_FIXTURE = (FIXTURE_DIR / "iw_station_clear.txt").read_text()
BLOCKED_FIXTURE = (FIXTURE_DIR / "iw_station_blocked.txt").read_text()
STALE_FIXTURE = (FIXTURE_DIR / "iw_station_stale.txt").read_text()

TEST_BSSID = "<bssid>"


# ---------------------------------------------------------------------------
# Regex parsing
# ---------------------------------------------------------------------------

class TestStationRegex:
    def test_parses_clear_fixture_signal(self):
        m = _SIGNAL_RE.search(CLEAR_FIXTURE)
        assert m is not None
        assert int(m.group(1)) == -62

    def test_parses_blocked_fixture_signal(self):
        m = _SIGNAL_RE.search(BLOCKED_FIXTURE)
        assert m is not None
        assert int(m.group(1)) == -67

    def test_parses_rx_packets(self):
        m = _RX_PACKETS_RE.search(CLEAR_FIXTURE)
        assert m is not None
        assert int(m.group(1)) == 1823

        m_blocked = _RX_PACKETS_RE.search(BLOCKED_FIXTURE)
        assert m_blocked is not None
        assert int(m_blocked.group(1)) == 1824

    def test_no_match_on_empty(self):
        assert _SIGNAL_RE.search("") is None
        assert _RX_PACKETS_RE.search("") is None

    def test_parse_station_output_helper(self):
        dbm, pkts = parse_station_output(CLEAR_FIXTURE)
        assert dbm == -62
        assert pkts == 1823


# ---------------------------------------------------------------------------
# _read_station_info (mocked subprocess)
# ---------------------------------------------------------------------------

class TestReadStationInfo:
    def test_returns_info_from_clear_fixture(self):
        with mock.patch(
            "radio.wifi_rssi.subprocess.check_output",
            return_value=CLEAR_FIXTURE.encode(),
        ):
            dbm, pkts = _read_station_info("wlan0", TEST_BSSID)
            assert dbm == -62
            assert pkts == 1823

    def test_returns_info_from_blocked_fixture(self):
        with mock.patch(
            "radio.wifi_rssi.subprocess.check_output",
            return_value=BLOCKED_FIXTURE.encode(),
        ):
            dbm, pkts = _read_station_info("wlan0", TEST_BSSID)
            assert dbm == -67
            assert pkts == 1824

    def test_returns_none_on_subprocess_error(self):
        with mock.patch(
            "radio.wifi_rssi.subprocess.check_output",
            side_effect=Exception("fail"),
        ):
            dbm, pkts = _read_station_info("wlan0", TEST_BSSID)
            assert dbm is None
            assert pkts is None

    def test_drop_between_clear_and_blocked(self):
        clear = -62
        blocked = -67
        drop = blocked - clear
        assert drop <= -3, f"Expected >= 3 dB drop, got {abs(drop)} dB"


# ---------------------------------------------------------------------------
# _make_message
# ---------------------------------------------------------------------------

class TestMakeMessage:
    def test_message_shape(self):
        payload = _make_message(-62, 7)
        msg = json.loads(payload)
        assert msg["v"] == 2
        assert msg["type"] == "rssi"
        assert msg["src"] == "live"
        assert msg["link"] == "pi5>unoq:wifi"
        assert msg["kind"] == "wifi"
        assert msg["tx"] == "pi5"
        assert msg["rx"] == "unoq"
        assert msg["dbm"] == -62
        assert msg["seq"] == 7
        assert isinstance(msg["t"], int)

    def test_seq_increments(self):
        m1 = json.loads(_make_message(-60, 0))
        m2 = json.loads(_make_message(-60, 1))
        assert m2["seq"] == m1["seq"] + 1

    def test_no_mac_in_payload(self):
        payload = _make_message(-62, 0).decode()
        assert not re.search(r"\b[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){5}\b", payload)


# ---------------------------------------------------------------------------
# run() — verify it sends UDP messages only when rx packets increase
# ---------------------------------------------------------------------------

class TestRunSendsUDP:
    def test_sends_messages_when_rx_packets_rise(self):
        """run() should send messages when rx packets counter increases."""
        received: list[bytes] = []
        stop = threading.Event()

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        sock.settimeout(0.1)
        port = sock.getsockname()[1]

        def collector():
            while not stop.is_set():
                try:
                    data, _ = sock.recvfrom(4096)
                    received.append(data)
                except (socket.timeout, OSError):
                    break

        t_collect = threading.Thread(target=collector, daemon=True)
        t_collect.start()

        # Simulate increasing rx packets on each call: 100, 101, 102, ...
        counter = {"pkt": 100}

        def fake_check_output(*args, **kwargs):
            counter["pkt"] += 1
            out = f"Station <bssid> (on wlan0)\n\trx packets:\t{counter['pkt']}\n\tsignal:\t-62 dBm\n"
            return out.encode()

        with mock.patch("radio.wifi_rssi.subprocess.check_output", side_effect=fake_check_output):
            t_run = threading.Thread(
                target=run,
                kwargs={
                    "iface": "wlan0",
                    "bssid": TEST_BSSID,
                    "bus_host": "127.0.0.1",
                    "bus_port": port,
                    "rate_hz": 25.0,
                },
                daemon=True,
            )
            t_run.start()
            time.sleep(0.4)

        stop.set()
        sock.close()

        assert len(received) >= 4, f"Only received {len(received)} messages"
        seqs = [json.loads(r)["seq"] for r in received]
        assert seqs == list(range(len(seqs))), "seq did not increment monotonically"

    def test_unchanged_rx_packets_does_not_send(self):
        """run() must not send messages when rx packets counter does not advance."""
        received: list[bytes] = []
        stop = threading.Event()

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        sock.settimeout(0.1)
        port = sock.getsockname()[1]

        def collector():
            while not stop.is_set():
                try:
                    data, _ = sock.recvfrom(4096)
                    received.append(data)
                except (socket.timeout, OSError):
                    break

        t_collect = threading.Thread(target=collector, daemon=True)
        t_collect.start()

        # Return static STALE_FIXTURE with unchanging rx packets: 1823
        with mock.patch(
            "radio.wifi_rssi.subprocess.check_output",
            return_value=STALE_FIXTURE.encode(),
        ):
            t_run = threading.Thread(
                target=run,
                kwargs={
                    "iface": "wlan0",
                    "bssid": TEST_BSSID,
                    "bus_host": "127.0.0.1",
                    "bus_port": port,
                    "rate_hz": 25.0,
                },
                daemon=True,
            )
            t_run.start()
            time.sleep(0.3)

        stop.set()
        sock.close()

        assert len(received) == 0, f"Expected 0 messages for unchanged packets, got {len(received)}"

    def test_raises_without_bssid(self):
        with pytest.raises(RuntimeError, match="WIFI_BSSID"):
            run(iface="wlan0", bssid="")


# ---------------------------------------------------------------------------
# report_wifi
# ---------------------------------------------------------------------------

class TestReportWifi:
    PASSING_MD = """
## Gate 1 — Wi-Fi link test (#19)

**Pass criteria:** ≥ 20 samples/s; a person in the line drops signal ≥ 3 dB, 3 out of 3 runs.

**Measured sample rate:** 24.6 samples/s

| Run | Baseline dBm | Blocked dBm | Drop dB | Result |
|-----|-------------|------------|---------|--------|
| 1   | -62         | -68        | 6.0     | PASS   |
| 2   | -62         | -68        | 6.0     | PASS   |
| 3   | -61         | -67        | 6.0     | PASS   |

**Overall Gate 1:** PASS
"""

    FAILING_MD_LOW_RATE = """
## Gate 1 — Wi-Fi link test (#19)

**Pass criteria:** ≥ 20 samples/s; a person in the line drops signal ≥ 3 dB, 3 out of 3 runs.

**Measured sample rate:** 15.0 samples/s

| Run | Baseline dBm | Blocked dBm | Drop dB | Result |
|-----|-------------|------------|---------|--------|
| 1   | -62         | -65        | 3.0     | PASS   |
| 2   | -63         | -66        | 3.0     | PASS   |
| 3   | -61         | -63        | 2.0     | FAIL   |
"""

    UNMEASURED_MD = """
## Gate 1 — Wi-Fi link test (#19)

**Pass criteria:** ≥ 20 samples/s; a person in the line drops signal ≥ 3 dB, 3 out of 3 runs.

**Measured sample rate:** __ samples/s

| Run | Baseline dBm | Blocked dBm | Drop dB | Result |
|-----|-------------|------------|---------|--------|
| 1   | __          | __         | __      | __     |
| 2   | __          | __         | __      | __     |
| 3   | __          | __         | __      | __     |
"""

    def test_parse_rate_ignores_criteria_line(self):
        """Must match the measured rate line, not the criteria line containing ≥ 20."""
        data = parse_gate_md(self.PASSING_MD)
        assert data["rate_hz"] == pytest.approx(24.6)

    def test_parse_rows(self):
        data = parse_gate_md(self.PASSING_MD)
        assert len(data["rows"]) == 3
        assert float(data["rows"][0]["drop"]) == 6.0

    def test_passing_gate(self):
        data = parse_gate_md(self.PASSING_MD)
        assert check(data) == []

    def test_failing_low_rate(self):
        data = parse_gate_md(self.FAILING_MD_LOW_RATE)
        failures = check(data)
        assert any("rate 15.0 < 20" in f for f in failures)

    def test_failing_low_drop(self):
        data = parse_gate_md(self.FAILING_MD_LOW_RATE)
        failures = check(data)
        assert any("2.0" in f or "drop" in f.lower() for f in failures)

    def test_unmeasured_gate(self):
        data = parse_gate_md(self.UNMEASURED_MD)
        failures = check(data)
        assert any("measured sample rate" in f for f in failures)
        assert any("not yet measured" in f for f in failures)
