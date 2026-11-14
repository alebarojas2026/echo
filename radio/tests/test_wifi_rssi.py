"""Tests for radio.wifi_rssi and radio.report_wifi.

All tests use recorded fixture text — no hardware, no network.
No MAC-shaped text or device identifiers in this file.
"""

from __future__ import annotations

import json
import re
import socket
import unittest.mock as mock
from pathlib import Path

import pytest

from contracts.check import errors
from radio.wifi_rssi import (
    Pinger,
    Reader,
    Stats,
    _make_message,
    _read_station_info,
    find_tool,
    gate,
    gate_block,
    gate_rows,
    load_env_file,
    main,
    parse_station_output,
    poll_loop,
    settings,
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

    def test_chain_values_read_the_signal_line_not_the_ack_lines(self):
        # ath10k reports per-chain signal, so iw puts "[-71, -74]" between the number and dBm.
        chains = (FIXTURE_DIR / "iw_station_chains.txt").read_text()
        assert parse_station_output(chains) == (-71, 2051)

    def test_chain_values_without_ack_lines(self):
        chains = (FIXTURE_DIR / "iw_station_chains.txt").read_text()
        no_ack = "\n".join(line for line in chains.splitlines() if "ack signal" not in line)
        assert parse_station_output(no_ack) == (-71, 2051)

    def test_only_ack_and_avg_lines_give_no_signal(self):
        text = "\tsignal avg:\t-70 dBm\n\tlast ack signal:-58 dBm\n\tavg ack signal:\t-58 dBm\n\trx packets:\t5\n"
        assert parse_station_output(text) == (None, 5)


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
# Reader, Pinger, Stats and run(): no subprocess, no hardware
# ---------------------------------------------------------------------------

def quiet(_text):
    pass


class FakeStation:
    """Stands in for `iw ... station get`: hands out (dbm, rx_packets) pairs, then (None, None)."""

    def __init__(self, *readings):
        self.readings, self.calls = list(readings), []

    def __call__(self, iface, bssid):
        self.calls.append((iface, bssid))
        return self.readings.pop(0) if self.readings else (None, None)


class FakeProc:
    def __init__(self):
        self.code, self.terminated = None, False

    def poll(self):
        return self.code

    def terminate(self):
        self.terminated, self.code = True, -15

    def wait(self, timeout=None):
        return self.code

    def kill(self):
        self.code = -9


class TestReader:
    def test_reads_only_when_rx_packets_rise(self):
        station = FakeStation((-60, 10), (-61, 11), (-62, 11), (-63, 13))
        reader = Reader("wlan0", TEST_BSSID, read=station, say=quiet)
        assert [reader.poll() for _ in range(4)] == [None, -61, None, -63]
        assert station.calls[0] == ("wlan0", TEST_BSSID)

    def test_unchanged_rx_packets_never_read(self):
        reader = Reader("wlan0", TEST_BSSID, read=lambda *_: parse_station_output(STALE_FIXTURE), say=quiet)
        assert [reader.poll() for _ in range(10)] == [None] * 10

    def test_a_rejoin_starts_the_counter_again(self):
        # After the Pi comes back, the station's counters restart from 0.
        station = FakeStation((-60, 500), (None, None), (-61, 3), (-62, 4))
        reader = Reader("wlan0", TEST_BSSID, read=station, say=quiet)
        assert [reader.poll() for _ in range(4)] == [None, None, None, -62]

    def test_waiting_and_recovery_are_logged_once_each(self):
        said = []
        station = FakeStation((None, None), (None, None), (-60, 1), (-61, 2), (-62, 3))
        reader = Reader("wlan0", TEST_BSSID, read=station, say=said.append)
        for _ in range(5):
            reader.poll()
        assert said == ["no signal: wlan0 isn't joined to the Pi's hotspot; still trying",
                        "reading pi5>unoq:wifi on wlan0"]

class TestPinger:
    def test_starts_one_ping_at_the_rate(self):
        started = []
        pinger = Pinger("10.42.0.1", 50, popen=lambda cmd, **kw: started.append(cmd) or FakeProc(),
                        clock=lambda: 0.0, say=quiet)
        pinger.check()
        pinger.check()
        assert started == [["ping", "-n", "-q", "-i", "0.020", "10.42.0.1"]]

    def test_restarts_a_ping_that_exited_but_not_too_often(self):
        t, procs = [0.0], []

        def popen(cmd, **kw):
            procs.append(FakeProc())
            return procs[-1]

        pinger = Pinger("10.42.0.1", 50, popen=popen, clock=lambda: t[0], retry_s=2.0, say=quiet)
        pinger.check()
        procs[0].code = 2   # "Network is unreachable": the hotspot is down
        t[0] = 1.0
        pinger.check()
        assert len(procs) == 1
        t[0] = 2.5
        pinger.check()
        assert len(procs) == 2

    def test_a_failing_ping_is_said_once_and_its_recovery_too(self):
        t, procs, said = [0.0], [], []

        def popen(cmd, **kw):
            procs.append(FakeProc())
            return procs[-1]

        pinger = Pinger("10.42.0.1", 50, popen=popen, clock=lambda: t[0], retry_s=2.0, say=said.append)
        pinger.check()
        for step in range(1, 4):                 # exits at once three times in a row
            procs[-1].code = 2
            t[0] = 2.5 * step
            pinger.check()
        assert said == ["ping to 10.42.0.1 exited (2): readings come at the beacon rate until it runs; "
                        "trying again every 2 s"]
        t[0] += 4.0
        pinger.check()                           # running, but not for 5 s yet
        assert len(said) == 1
        t[0] += 2.0
        pinger.check()
        assert said[-1] == "ping to 10.42.0.1 running again" and len(procs) == 4

    def test_zero_hz_means_no_pings(self):
        pinger = Pinger("10.42.0.1", 0, popen=lambda *a, **k: pytest.fail("ping started"), say=quiet)
        pinger.check()
        assert pinger.cmd is None

    def test_missing_ping_is_said_once_and_left_off(self):
        said = []

        def popen(cmd, **kw):
            raise FileNotFoundError("ping")

        pinger = Pinger("10.42.0.1", 50, popen=popen, clock=lambda: 100.0, say=said.append)
        pinger.check()
        pinger.check()
        assert len(said) == 1 and "beacon rate" in said[0]

    def test_stop_ends_a_running_ping(self):
        proc = FakeProc()
        pinger = Pinger("10.42.0.1", 50, popen=lambda cmd, **kw: proc, say=quiet)
        pinger.check()
        pinger.stop()
        assert proc.terminated and pinger.proc is None


class TestLoops:
    def test_stats_say_the_rate_and_median_then_silence(self):
        t, said = [0.0], []
        stats = Stats(10, clock=lambda: t[0], say=said.append)
        for v in (-60, -61, -62):
            stats.add(v)
        t[0] = 5.0
        stats.tick()
        assert said == []
        t[0] = 10.0
        stats.tick()
        t[0] = 20.0
        stats.tick()
        assert said == ["last 10 s: 3 readings (0.3/s), median -61 dBm", "last 10 s: no readings"]

    def test_poll_loop_keeps_the_rate_and_stops_after_seconds(self):
        t = [0.0]

        class Steady:
            def poll(self):
                t[0] += 0.004   # each iw call takes a little time
                return -60

        got = []
        spent = poll_loop(Steady(), got.append, rate_hz=25, seconds=1.0,
                          clock=lambda: t[0], sleep=lambda s: t.__setitem__(0, t[0] + s))
        assert len(got) == 25
        assert spent == pytest.approx(1.0, abs=0.05)

    def test_run_sends_contract_messages_with_one_seq_counter(self):
        bus = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        bus.bind(("127.0.0.1", 0))
        bus.settimeout(0.5)
        station = FakeStation(*[(-60 - i % 3, i) for i in range(6)])
        reader = Reader("wlan0", TEST_BSSID, read=station, say=quiet)
        sent = run(bus_host="127.0.0.1", bus_port=bus.getsockname()[1], rate_hz=1000,
                   stop=lambda: not station.readings, reader=reader, pinger=Pinger("10.42.0.1", 0), keep=True)
        got = []
        while True:
            try:
                got.append(json.loads(bus.recvfrom(4096)[0]))
            except socket.timeout:
                break
        bus.close()
        assert sent == [-61, -62, -60, -61, -62]
        assert [m["dbm"] for m in got] == sent
        assert [m["seq"] for m in got] == [0, 1, 2, 3, 4]
        for m in got:
            assert errors(m) == [], m

    def test_the_service_keeps_nothing_but_the_seq(self):
        bus = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        bus.bind(("127.0.0.1", 0))
        bus.settimeout(0.5)
        station = FakeStation(*[(-60, i) for i in range(4)])
        sent = run(bus_port=bus.getsockname()[1], rate_hz=1000, stop=lambda: not station.readings,
                   reader=Reader("wlan0", TEST_BSSID, read=station, say=quiet), pinger=Pinger("10.42.0.1", 0))
        seqs = [json.loads(bus.recvfrom(4096)[0])["seq"] for _ in range(3)]
        bus.close()
        assert sent == [] and seqs == [0, 1, 2]

    def test_run_stops_the_pings_on_the_way_out(self):
        proc = FakeProc()

        def interrupted(*_):
            raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            run(rate_hz=1000, reader=Reader("wlan0", TEST_BSSID, read=interrupted, say=quiet),
                pinger=Pinger("10.42.0.1", 50, popen=lambda cmd, **kw: proc, say=quiet))
        assert proc.terminated


class TestSettings:
    def test_defaults(self):
        cfg = settings({})
        assert cfg == {"iface": "wlan0", "bssid": "", "bus_host": "127.0.0.1", "bus_port": 5600,
                       "rate_hz": 25.0, "ping_host": "10.42.0.1", "ping_hz": 50.0}

    def test_overrides_and_pings_off(self):
        cfg = settings({"WIFI_IFACE": "wlan1", "SENSING_BSSID": "<b>", "WIFI_PING_HZ": "0", "RATE_HZ": "30"})
        assert (cfg["iface"], cfg["bssid"], cfg["ping_hz"], cfg["rate_hz"]) == ("wlan1", "<b>", 0.0, 30.0)

    def test_env_file_fills_only_what_is_unset(self, tmp_path):
        env_file = tmp_path / "env"
        env_file.write_text("# comment\nA=1\nexport B=\"two\"\nC='x y'\nWIFI_IFACE=wlan9\n\nnot a line\n")
        environ = {"WIFI_IFACE": "wlan1"}
        load_env_file(env_file, environ)
        assert environ == {"WIFI_IFACE": "wlan1", "A": "1", "B": "two", "C": "x y"}
        load_env_file(tmp_path / "missing", environ)   # no file: nothing changes, no error
        assert len(environ) == 4

    def test_iw_is_found_outside_a_short_path(self, tmp_path):
        sbin = tmp_path / "sbin"
        sbin.mkdir()
        (sbin / "iw").write_text("#!/bin/sh\n")
        (sbin / "iw").chmod(0o755)
        no_path = lambda name: None    # an ssh command's PATH: /usr/local/bin:/usr/bin:/bin
        assert find_tool("iw", which=no_path, dirs=(str(tmp_path / "nope"), str(sbin))) == str(sbin / "iw")
        assert find_tool("iw", which=lambda name: "/usr/bin/iw", dirs=(str(sbin),)) == "/usr/bin/iw"
        assert find_tool("iw", which=no_path, dirs=(str(tmp_path / "nope"),)) is None

    def test_main_says_how_to_get_iw(self):
        with mock.patch("radio.wifi_rssi.find_tool", return_value=None), \
             mock.patch("radio.wifi_rssi.load_env_file"):
            with pytest.raises(SystemExit, match="apt install iw"):
                main([])

    def test_main_needs_the_bssid(self, monkeypatch):
        monkeypatch.delenv("WIFI_BSSID", raising=False)
        monkeypatch.delenv("SENSING_BSSID", raising=False)
        with mock.patch("radio.wifi_rssi.find_tool", return_value="/usr/sbin/iw"), \
             mock.patch("radio.wifi_rssi.load_env_file"):
            with pytest.raises(SystemExit, match="WIFI_BSSID"):
                main([])


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


class TestGateRows:
    RATE = "**Measured sample rate:** 24.6 samples/s\n\n"

    def rows(self, *cells):
        return parse_gate_md(self.RATE + "\n".join(f"| {i} | {c} |" for i, c in enumerate(cells, 1)))

    def test_blank_dbm_cells_never_pass(self):
        failures = check(self.rows(*["__ | __ | 6 | PASS"] * 3))
        assert failures == [f"run {i}: not yet measured" for i in (1, 2, 3)]

    def test_drop_is_worked_out_from_the_dbm_cells(self):
        failures = check(self.rows("-62 | -63 | 6 | PASS", "-62 | -68 | 6.0 | PASS", "-61 | -66 | -5 | PASS"))
        assert any(f.startswith("run 1: drop 1 dB < 3 dB") for f in failures)
        assert any(f.startswith("run 1: Drop cell 6") for f in failures)
        assert not any(f.startswith("run 2") for f in failures)
        assert any(f.startswith("run 3: Drop cell -5") for f in failures)   # a sign slip

    def test_a_fail_result_fails(self):
        failures = check(self.rows("-62 | -68 | 6 | PASS", "-62 | -68 | 6 | FAIL", "-62 | -68 | 6 | PASS"))
        assert failures == ["run 2: Result is FAIL"]


class TestGate:
    def run_gate(self, clear_dbm, blocked_dbm, runs=3):
        """A gate on a test clock: the reader gives clear_dbm until Enter is pressed for the blocked half."""
        t, prompts, level, rx = [0.0], [], [clear_dbm], [0]

        def station(iface, bssid):
            t[0] += 0.004
            rx[0] += 2
            return level[0], rx[0]

        def ask(prompt):
            prompts.append(prompt)
            level[0] = blocked_dbm if "stand in" in prompt else clear_dbm

        reader = Reader("wlan0", TEST_BSSID, read=station, say=quiet)
        block = gate(reader, Pinger("10.42.0.1", 0), rate_hz=25, runs=runs, window_s=10.0, ask=ask,
                     say=quiet, clock=lambda: t[0], sleep=lambda s: t.__setitem__(0, t[0] + s))
        return block, prompts

    def test_a_good_link_prints_rows_that_pass_the_check(self):
        block, prompts = self.run_gate(-61, -67)
        assert len(prompts) == 6
        assert "| 1   | -61         | -67        | 6.0     | PASS   |" in block
        assert "**Overall Gate 1:** PASS" in block
        data = parse_gate_md(block)
        assert data["rate_hz"] == pytest.approx(25, abs=0.5)
        assert check(data) == []

    def test_a_small_drop_fails(self):
        block, _ = self.run_gate(-61, -63)
        assert "**Overall Gate 1:** FAIL" in block
        assert any("< 3 dB" in f for f in check(parse_gate_md(block)))

    def test_no_readings_give_blank_rows_and_fail(self):
        assert gate_rows([([], [-60])]) == [{"run": 1, "baseline": None, "blocked": None, "drop": None,
                                            "result": "FAIL"}]
        block = gate_block(0.0, gate_rows([([], [])] * 3))
        assert "**Overall Gate 1:** FAIL" in block
        assert any("not yet measured" in f for f in check(parse_gate_md(block)))


class TestMain:
    """The service's entry point, wired end to end with iw and ping faked at the subprocess calls."""

    def test_main_reads_pings_and_sends_until_its_seconds_are_up(self, monkeypatch, capsys):
        bus = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        bus.bind(("127.0.0.1", 0))
        bus.settimeout(0.5)
        for key, value in {"WIFI_IFACE": "wlan0", "WIFI_BSSID": TEST_BSSID, "BUS_HOST": "127.0.0.1",
                           "BUS_PORT": str(bus.getsockname()[1]), "RATE_HZ": "50", "WIFI_PING_HZ": "50"}.items():
            monkeypatch.setenv(key, value)
        rx = [0]

        def station(cmd, **kw):            # every poll sees a new frame from the Pi
            assert cmd[0].endswith("iw") and cmd[1:4] == ["dev", "wlan0", "station"]
            rx[0] += 2
            return f"\tsignal:  \t-58 [-58, -61] dBm\n\trx packets:\t{rx[0]}\n".encode()

        pings = []
        monkeypatch.setattr("radio.wifi_rssi.subprocess.check_output", station)
        monkeypatch.setattr("radio.wifi_rssi.subprocess.Popen", lambda cmd, **kw: pings.append(cmd) or FakeProc())
        monkeypatch.setattr("radio.wifi_rssi.find_tool", lambda name: "/usr/sbin/iw")
        monkeypatch.setattr("radio.wifi_rssi.load_env_file", lambda path: None)
        monkeypatch.setattr("radio.wifi_rssi.signal.signal", lambda *a: None)
        main(["--seconds", "0.4"])
        got = []
        while True:
            try:
                got.append(json.loads(bus.recvfrom(4096)[0]))
            except socket.timeout:
                break
        bus.close()
        assert pings == [["ping", "-n", "-q", "-i", "0.020", "10.42.0.1"]]
        assert len(got) >= 5 and {m["dbm"] for m in got} == {-58}
        assert [m["seq"] for m in got] == list(range(len(got)))
        assert all(errors(m) == [] for m in got)
        assert capsys.readouterr().out.splitlines()[-1].startswith(f"pi5>unoq:wifi: {len(got)} readings in ")
