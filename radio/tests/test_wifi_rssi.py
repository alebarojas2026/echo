"""Tests for radio.wifi_rssi and radio.report_wifi.

All tests use recorded fixture text — no hardware, no network.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import unittest.mock as mock
from pathlib import Path

import pytest

from radio.wifi_rssi import _make_message, _read_rssi_dbm, _SIGNAL_RE, run
from radio.report_wifi import parse_gate_md, check

FIXTURE_DIR = Path(__file__).parent / "fixtures"
CLEAR_FIXTURE = (FIXTURE_DIR / "iw_station_clear.txt").read_text()
BLOCKED_FIXTURE = (FIXTURE_DIR / "iw_station_blocked.txt").read_text()


# ---------------------------------------------------------------------------
# _SIGNAL_RE parsing
# ---------------------------------------------------------------------------

class TestSignalRegex:
    def test_parses_clear_fixture(self):
        m = _SIGNAL_RE.search(CLEAR_FIXTURE)
        assert m is not None
        assert int(m.group(1)) == -62

    def test_parses_blocked_fixture(self):
        m = _SIGNAL_RE.search(BLOCKED_FIXTURE)
        assert m is not None
        assert int(m.group(1)) == -67

    def test_no_match_on_empty(self):
        assert _SIGNAL_RE.search("") is None

    def test_no_match_on_command_not_found(self):
        assert _SIGNAL_RE.search("command failed: No such device") is None


# ---------------------------------------------------------------------------
# _read_rssi_dbm (mocked subprocess)
# ---------------------------------------------------------------------------

class TestReadRssiDbm:
    def test_returns_dbm_from_clear_fixture(self):
        with mock.patch(
            "radio.wifi_rssi.subprocess.check_output",
            return_value=CLEAR_FIXTURE.encode(),
        ):
            assert _read_rssi_dbm("wlan0", "aa:bb:cc:dd:ee:ff") == -62

    def test_returns_dbm_from_blocked_fixture(self):
        with mock.patch(
            "radio.wifi_rssi.subprocess.check_output",
            return_value=BLOCKED_FIXTURE.encode(),
        ):
            assert _read_rssi_dbm("wlan0", "aa:bb:cc:dd:ee:ff") == -67

    def test_returns_none_on_subprocess_error(self):
        with mock.patch(
            "radio.wifi_rssi.subprocess.check_output",
            side_effect=Exception("fail"),
        ):
            assert _read_rssi_dbm("wlan0", "aa:bb:cc:dd:ee:ff") is None

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
        # MAC-like patterns must not appear
        import re
        assert not re.search(r"\b[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){5}\b", payload)


# ---------------------------------------------------------------------------
# run() — verify it sends UDP messages at the target rate
# ---------------------------------------------------------------------------

class TestRunSendsUDP:
    def test_sends_messages_to_bus(self):
        """run() must send >= 5 valid rssi messages in 0.5 s at 25 Hz."""
        received: list[bytes] = []
        stop = threading.Event()

        # Bind a local UDP socket to catch messages.
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        sock.settimeout(0.1)
        port = sock.getsockname()[1]

        def collector():
            while not stop.is_set():
                try:
                    data, _ = sock.recvfrom(4096)
                    received.append(data)
                except socket.timeout:
                    pass

        t_collect = threading.Thread(target=collector, daemon=True)
        t_collect.start()

        # Patch subprocess so no hardware is needed.
        with mock.patch(
            "radio.wifi_rssi.subprocess.check_output",
            return_value=CLEAR_FIXTURE.encode(),
        ):
            t_run = threading.Thread(
                target=run,
                kwargs={
                    "iface": "wlan0",
                    "bssid": "aa:bb:cc:dd:ee:ff",
                    "bus_host": "127.0.0.1",
                    "bus_port": port,
                    "rate_hz": 25.0,
                },
                daemon=True,
            )
            t_run.start()
            time.sleep(0.5)

        stop.set()
        sock.close()

        assert len(received) >= 5, f"Only received {len(received)} messages in 0.5 s"
        for raw in received:
            msg = json.loads(raw)
            assert msg["v"] == 2
            assert msg["type"] == "rssi"
            assert msg["link"] == "pi5>unoq:wifi"

    def test_raises_without_bssid(self):
        with pytest.raises(RuntimeError, match="WIFI_BSSID"):
            run(iface="wlan0", bssid="")


# ---------------------------------------------------------------------------
# report_wifi
# ---------------------------------------------------------------------------

class TestReportWifi:
    PASSING_MD = """
## Gate 1 — Wi-Fi link test

samples/s: 24.3

| Run | Baseline dBm | Blocked dBm | Drop dB | Result |
|-----|-------------|------------|---------|--------|
| 1   | -62         | -67        | 5       | PASS   |
| 2   | -63         | -68        | 5       | PASS   |
| 3   | -61         | -66        | 5       | PASS   |
"""

    FAILING_MD_LOW_RATE = """
## Gate 1 — Wi-Fi link test

samples/s: 15.0

| Run | Baseline dBm | Blocked dBm | Drop dB | Result |
|-----|-------------|------------|---------|--------|
| 1   | -62         | -65        | 3       | PASS   |
| 2   | -63         | -66        | 3       | PASS   |
| 3   | -61         | -63        | 2       | FAIL   |
"""

    def test_parse_rate(self):
        data = parse_gate_md(self.PASSING_MD)
        assert data["rate_hz"] == pytest.approx(24.3)

    def test_parse_rows(self):
        data = parse_gate_md(self.PASSING_MD)
        assert len(data["rows"]) == 3

    def test_passing_gate(self):
        data = parse_gate_md(self.PASSING_MD)
        assert check(data) == []

    def test_failing_low_rate(self):
        data = parse_gate_md(self.FAILING_MD_LOW_RATE)
        failures = check(data)
        assert any("rate" in f for f in failures)

    def test_failing_low_drop(self):
        data = parse_gate_md(self.FAILING_MD_LOW_RATE)
        failures = check(data)
        # run 3 has a 2 dB drop which is < 3 dB
        assert any("2.0" in f or "drop" in f.lower() for f in failures)

    def test_missing_rows(self):
        data = parse_gate_md("samples/s: 25")
        failures = check(data)
        assert any("run" in f.lower() for f in failures)
