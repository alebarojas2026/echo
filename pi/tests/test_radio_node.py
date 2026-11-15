"""Tests for pi.radio_node against hand-built HCI packets and fake controller."""

import json
import socket
import struct
import pytest

from contracts.check import errors
from radio import hci
from radio.tests.fakes import FakeController, fixture
from pi.radio_node import (
    ADV_INTERVAL_HCI,
    LE_SET_ADV_PARAMS,
    LE_SET_ADV_DATA,
    LE_SET_ADV_ENABLE,
    build_adv_params_params,
    build_adv_params_cmd,
    build_adv_data_params,
    build_adv_data_cmd,
    build_adv_enable_cmd,
    run,
)


def test_adv_params_parameter_bytes():
    """Verify the 15 parameter bytes: interval 0x0020 twice, type 0x03, channel map 0x07."""
    params = build_adv_params_params()
    assert len(params) == 15
    min_int, max_int = struct.unpack_from("<HH", params, 0)
    assert min_int == 0x0020
    assert max_int == 0x0020
    adv_type = params[4]
    assert adv_type == 0x03  # ADV_NONCONN_IND
    channel_map = params[13]
    assert channel_map == 0x07  # all 3 advert channels (37, 38, 39)
    filter_policy = params[14]
    assert filter_policy == 0x00


def test_adv_params_command_packet():
    cmd = build_adv_params_cmd()
    assert cmd[0] == 0x01  # CMD_PKT
    opcode = struct.unpack_from("<H", cmd, 1)[0]
    assert opcode == LE_SET_ADV_PARAMS
    param_len = cmd[3]
    assert param_len == 15


def test_adv_data_command_packet():
    cmd = build_adv_data_cmd()
    assert cmd[0] == 0x01
    opcode = struct.unpack_from("<H", cmd, 1)[0]
    assert opcode == LE_SET_ADV_DATA
    param_len = cmd[3]
    assert param_len == 32
    # Verify manufacturer payload FFFF 52 53 53 ('S')
    assert bytes.fromhex("FFFF525353") in cmd


def test_adv_enable_command():
    cmd_on = build_adv_enable_cmd(True)
    cmd_off = build_adv_enable_cmd(False)
    assert cmd_on == bytes.fromhex("01 0a 20 01 01")
    assert cmd_off == bytes.fromhex("01 0a 20 01 00")


def test_startup_sequence_and_packet_forwarding():
    """Verify advertising is configured and enabled, scan is started, and packets are forwarded."""
    events = [
        fixture("legacy_report_east"),
        fixture("legacy_reports_three"),        # contains west (-70) and pi5 (-80)
        fixture("legacy_report_near_misses"),    # unknown beacons
    ]
    fake = FakeController(events=events, ext=False)
    dev = hci.Hci(fake)

    # UDP receiver to capture bus messages
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    srv.settimeout(0.5)
    host, port = srv.getsockname()

    seen = run(dev, bus_host=host, bus_port=port, stop=lambda: fake.drained)

    received = []
    while True:
        try:
            data, _ = srv.recvfrom(4096)
            received.append(json.loads(data.decode()))
        except socket.timeout:
            break
    srv.close()

    # 1. Startup sequence opcodes checked against fake:
    # adv off, adv params, adv data, adv on, read supported, scan off, scan params, scan on ...
    assert LE_SET_ADV_ENABLE in fake.opcodes
    assert LE_SET_ADV_PARAMS in fake.opcodes
    assert LE_SET_ADV_DATA in fake.opcodes
    assert hci.LE_SET_SCAN_PARAMS in fake.opcodes
    assert hci.LE_SET_SCAN_ENABLE in fake.opcodes

    # 2. Pi receives east (-61) and west (-70). Pi never emits for itself.
    assert len(received) == 2
    assert [m["link"] for m in received] == ["east>pi5:ble", "west>pi5:ble"]

    # 3. Check every message conforms to contract v2
    for msg in received:
        errs = errors(msg)
        assert errs == [], f"Contract error in {msg}: {errs}"
        assert msg["rx"] == "pi5"
        assert msg["kind"] == "ble"
        assert msg["src"] == "live"

    # 4. Seq starts at 0 and increments
    assert [m["seq"] for m in received] == [0, 1]

    # 5. On exit, scan and advertising are turned off
    assert fake.sent[-1] == hci.command_packet(LE_SET_ADV_ENABLE, bytes([0x00]))


def test_controller_with_ext_scan_uses_legacy_opcodes_only():
    """Even when controller supports extended scanning (read_supported_commands_ext.hex),
    Pi must stay strictly legacy to avoid mixing advertising and scan command families."""
    fake = FakeController(ext=True)
    dev = hci.Hci(fake)

    run(dev, seconds=0.01, stop=lambda: True)

    assert hci.LE_SET_EXT_SCAN_PARAMS not in fake.opcodes
    assert hci.LE_SET_EXT_SCAN_ENABLE not in fake.opcodes
    assert hci.LE_SET_SCAN_PARAMS in fake.opcodes
    assert hci.LE_SET_SCAN_ENABLE in fake.opcodes



# Failure paths: no Ethernet, the board not listening, the controller reset or gone

import errno
import os

from pi import radio_node

RESET_COMPLETE = bytes.fromhex("04 0e 04 01 03 0c 00")  # Command Complete for HCI_Reset, status 0
ADV_ON = hci.command_packet(LE_SET_ADV_ENABLE, b"\x01")


class FlakySock:
    """A bus socket whose first `fail` sends raise like an unplugged Ethernet port."""

    def __init__(self, fail, err=errno.ENETUNREACH):
        self.fail, self.err, self.sent = fail, err, []

    def sendto(self, data, addr):
        if self.fail:
            self.fail -= 1
            raise OSError(self.err, os.strerror(self.err))
        self.sent.append(json.loads(data))

    def close(self):
        pass


class Clock:
    """time.monotonic stand-in that moves `step` seconds per call."""

    def __init__(self, step):
        self.now, self.step = 0.0, step

    def __call__(self):
        self.now += self.step
        return self.now


def loops(n):
    """stop() that ends the run after n turns of the loop."""
    left = [n]

    def stop():
        left[0] -= 1
        return left[0] < 0
    return stop


def test_no_ethernet_keeps_the_beacon_and_scan_going_and_recovers():
    events = [fixture("legacy_report_east"), fixture("legacy_reports_three"), fixture("legacy_report_east")]
    fake = FakeController(events=events)
    sock = FlakySock(fail=2)
    seen = run(hci.Hci(fake), bus_sock=sock, stop=lambda: fake.drained, seen={}, log=lambda line: None)

    assert seen == {"east>pi5:ble": [-61, -61], "west>pi5:ble": [-70]}
    assert [m["link"] for m in sock.sent] == ["east>pi5:ble"]  # the link came back for the third reading
    assert errors(sock.sent[0]) == []
    assert fake.sent.count(ADV_ON) == 1  # advertising was never dropped by the failed sends
    assert fake.sent[-1] == hci.command_packet(LE_SET_ADV_ENABLE, b"\x00")


def test_board_not_listening_is_not_an_error():
    closed = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    closed.bind(("127.0.0.1", 0))
    host, port = closed.getsockname()
    closed.close()  # nothing listens on this port now
    fake = FakeController(events=[fixture("legacy_report_east")] * 3)
    seen = run(hci.Hci(fake), bus_host=host, bus_port=port, stop=lambda: fake.drained, seen={},
               log=lambda line: None)
    assert seen == {"east>pi5:ble": [-61] * 3}


def test_status_line_counts_rates_and_failed_sends(monkeypatch):
    monkeypatch.setattr(radio_node, "QUIET_S", 1000.0)
    fake = FakeController(events=[fixture("legacy_report_east")] * 4)
    lines = []
    run(hci.Hci(fake), bus_sock=FlakySock(fail=1), stop=loops(10), clock=Clock(1.0), log=lines.append)
    status = [line for line in lines if "/s" in line]
    assert len(status) == 1
    assert "east>pi5:ble 0.4/s" in status[0] and "west>pi5:ble 0.0/s" in status[0]
    assert f"sent 3, not sent 1 ({os.strerror(errno.ENETUNREACH)})" in status[0]


def test_reset_by_bluetoothd_sets_advertising_and_scanning_up_again(monkeypatch):
    monkeypatch.setattr(radio_node, "SETTLE_S", 0.0)
    events = [fixture("legacy_report_east"), RESET_COMPLETE, fixture("legacy_report_east")]
    fake = FakeController(events=events)
    lines = []
    seen = run(hci.Hci(fake), bus_sock=FlakySock(fail=0), stop=lambda: fake.drained, seen={}, log=lines.append)

    setup = [LE_SET_ADV_ENABLE, LE_SET_ADV_PARAMS, LE_SET_ADV_DATA, LE_SET_ADV_ENABLE,
             hci.LE_SET_SCAN_ENABLE, hci.LE_SET_SCAN_PARAMS, hci.LE_SET_SCAN_ENABLE]
    ops = fake.opcodes
    first = ops.index(LE_SET_ADV_PARAMS) - 1
    assert ops[first:first + 7] == setup
    assert ops[first + 7:first + 14] == setup  # the whole setup again after the reset
    assert fake.sent.count(ADV_ON) == 2
    assert any("0x0C03" in line for line in lines)
    assert seen == {"east>pi5:ble": [-61, -61]}


def test_waits_for_the_other_side_to_finish_before_setting_up_again(monkeypatch):
    monkeypatch.setattr(radio_node, "QUIET_S", 1000.0)
    scan_off_by_someone = bytes.fromhex("04 0e 04 01 0c 20 00")
    fake = FakeController(events=[RESET_COMPLETE, scan_off_by_someone])
    run(hci.Hci(fake), bus_sock=FlakySock(fail=0), stop=loops(6), clock=Clock(0.4), log=lambda line: None)
    assert fake.sent.count(ADV_ON) == 2  # two outside changes 0.4 s apart: one setup, 1 s after the last


def test_silent_controller_is_set_up_again(monkeypatch):
    fake = FakeController()
    lines = []
    run(hci.Hci(fake), bus_sock=FlakySock(fail=0), stop=loops(12), clock=Clock(1.0), log=lines.append)
    assert fake.sent.count(ADV_ON) == 3  # at start, then after 5 s and 10 s of silence
    assert sum("no adverts" in line for line in lines) == 1


class DeadController(FakeController):
    """Bluetooth powered off: every send fails like a raw HCI socket on a down device."""

    def send(self, packet):
        raise OSError(errno.ENETDOWN, os.strerror(errno.ENETDOWN))


@pytest.mark.parametrize("fake", [
    DeadController(),                                                        # off when the node starts
    FakeController(events=[fixture("legacy_report_east")],
                   at_end=OSError(errno.EPIPE, os.strerror(errno.EPIPE))),   # unplugged while running
], ids=["down", "gone"])
def test_controller_down_or_gone_exits_nonzero_for_systemd(monkeypatch, fake):
    monkeypatch.setattr(radio_node, "open_controller", lambda dev: hci.Hci(fake))
    with pytest.raises(SystemExit) as stopped:
        radio_node.main(["--seconds", "5"])
    assert stopped.value.code not in (0, None)
    assert "Is Bluetooth on?" in str(stopped.value.code)


class Floors(FakeController):
    """A controller that answers 0x12 to LE Set Advertising Parameters below a floor per advertising type.

    floors: {type byte: lowest interval it takes, in 0.625 ms units, or None for never}. A type not
    listed takes anything.
    """

    def __init__(self, floors=None, **kw):
        super().__init__(**kw)
        self.floors = floors or {}

    def send(self, packet):
        if struct.unpack_from("<H", packet, 1)[0] == LE_SET_ADV_PARAMS:
            interval, kind = struct.unpack_from("<H", packet, 4)[0], packet[8]
            floor = self.floors.get(kind, 0)
            self.status[LE_SET_ADV_PARAMS] = 0x12 if floor is None or interval < floor else 0
        super().send(packet)

    @property
    def adverts(self):
        """(interval in ms, advertising type) of every LE Set Advertising Parameters sent."""
        return [(struct.unpack_from("<H", p, 4)[0] * 0.625, p[8]) for p in self.sent
                if struct.unpack_from("<H", p, 1)[0] == LE_SET_ADV_PARAMS]


CONN, SCAN, NONCONN = 0x00, 0x02, 0x03
PI_B = {CONN: 0x20, SCAN: 0xA0, NONCONN: 0xA0}    # the 4.x rule: 100 ms for scannable and non-connectable


def test_a_controller_that_takes_anything_gets_connectable_20_ms():
    fake = Floors(events=[fixture("legacy_report_east")])
    lines = []
    run(hci.Hci(fake), bus_sock=FlakySock(fail=0), stop=lambda: fake.drained, log=lines.append)
    assert fake.adverts == [(20, CONN)]   # nothing can beat 20 ms, so no other type is tried
    assert fake.sent.count(ADV_ON) == 1
    assert "[pi.radio_node] beacon S: advertising every 20 ms, connectable (ADV_IND); refused: nothing; " \
           "anything that connects is dropped at once" in lines


def test_the_4x_rule_keeps_connectable_20_ms_and_tries_nothing_slower():
    fake = Floors(PI_B, events=[fixture("legacy_report_east")])
    run(hci.Hci(fake), bus_sock=FlakySock(fail=0), stop=lambda: fake.drained, log=lambda line: None)
    assert fake.adverts == [(20, CONN)]


@pytest.mark.parametrize("floors, tried, kept, refused", [
    # connectable from 30 ms, scannable from 20 ms: scannable wins, and the controller is left on it
    ({CONN: 0x30, SCAN: 0x20}, [(20, CONN), (30, CONN), (20, SCAN)], (20, SCAN), "connectable 20 ms"),
    # connectable from 40, the others never: 40 ms connectable
    ({CONN: 0x40, SCAN: None, NONCONN: None},
     [(20, CONN), (30, CONN), (40, CONN), (20, SCAN), (30, SCAN), (20, NONCONN), (30, NONCONN)],
     (40, CONN), "connectable 20, 30 ms; scannable 20, 30 ms; non-connectable 20, 30 ms"),
    # connectable never, scannable from 50, non-connectable from 30: non-connectable 30, then set back to it
    ({CONN: None, SCAN: 0x50, NONCONN: 0x30},
     [(20, CONN), (30, CONN), (40, CONN), (50, CONN), (60, CONN), (80, CONN), (100, CONN),
      (20, SCAN), (30, SCAN), (40, SCAN), (50, SCAN), (20, NONCONN), (30, NONCONN)],
     (30, NONCONN), "connectable 20, 30, 40, 50, 60, 80, 100 ms; scannable 20, 30, 40 ms; non-connectable 20 ms"),
    # a tie goes to the earlier type: scannable 30 = connectable 30, so connectable is set again
    ({CONN: 0x30, SCAN: 0x30, NONCONN: 0x30},
     [(20, CONN), (30, CONN), (20, SCAN), (20, NONCONN)], (30, CONN),
     "connectable 20 ms; scannable 20 ms; non-connectable 20 ms"),
], ids=["scannable-wins", "connectable-40", "non-connectable-30", "tie"])
def test_the_ladder_keeps_the_fastest_type_and_interval(floors, tried, kept, refused):
    fake = Floors(floors)   # in 0.625 ms units: 0x20 = 20 ms, 0x30 = 30 ms, 0x40 = 40 ms, 0x50 = 50 ms
    lines = []
    run(hci.Hci(fake), bus_sock=FlakySock(fail=0), stop=lambda: True, log=lines.append)
    sent = fake.adverts
    assert sent[:len(tried)] == tried
    assert sent[-1] == kept                       # the controller holds what was kept
    told = [line for line in lines if "advertising every" in line]
    names = {CONN: "connectable (ADV_IND)", SCAN: "scannable (ADV_SCAN_IND)", NONCONN: "non-connectable (ADV_NONCONN_IND)"}
    assert told[0].startswith(f"[pi.radio_node] beacon S: advertising every {kept[0]:g} ms, {names[kept[1]]}; "
                              f"refused: {refused}")


def test_a_controller_that_refuses_below_100_ms_gets_100_ms():
    fake = Floors({CONN: 0xA0, SCAN: 0xA0, NONCONN: 0xA0}, events=[fixture("legacy_report_east")])
    lines = []
    run(hci.Hci(fake), bus_sock=FlakySock(fail=0), stop=lambda: fake.drained, log=lines.append)
    assert fake.adverts[-1] == (100, CONN)
    assert [a for a in fake.adverts if a[1] != CONN] == [(s, k) for k in (SCAN, NONCONN) for s in (20, 30, 40, 50, 60, 80)]
    assert any("advertising every 100 ms, connectable (ADV_IND)" in line for line in lines)


def test_one_type_by_hand_walks_only_that_type():
    fake = Floors({NONCONN: 0xA0})
    run(hci.Hci(fake), bus_sock=FlakySock(fail=0), stop=lambda: True, log=lambda line: None,
        adv_mode="non-connectable")
    assert fake.adverts == [(ms, NONCONN) for ms in (20, 30, 40, 50, 60, 80, 100)]


def test_one_type_refused_everywhere_falls_back_to_the_others():
    fake = Floors({SCAN: None})
    run(hci.Hci(fake), bus_sock=FlakySock(fail=0), stop=lambda: True, log=lambda line: None, adv_mode="scannable")
    assert fake.adverts[-1] == (20, CONN)


def test_everything_refused_is_an_error_for_systemd():
    fake = Floors({CONN: None, SCAN: None, NONCONN: None})
    with pytest.raises(hci.HciError, match="every advertising type was refused"):
        run(hci.Hci(fake), bus_sock=FlakySock(fail=0), stop=lambda: True, log=lambda line: None)


@pytest.mark.parametrize("value, dev", [("0", 0), ("hci0", 0), ("1", 1), ("hci1", 1), (" hci0 ", 0)])
def test_hci_iface_takes_a_number_or_a_name(monkeypatch, value, dev):
    import importlib
    monkeypatch.setenv("HCI_IFACE", value)
    try:
        assert importlib.reload(radio_node).HCI_IDX == dev
    finally:
        monkeypatch.delenv("HCI_IFACE")
        importlib.reload(radio_node)


def test_summary_gives_the_lowest_and_median_10s_rate():
    seen = {"east>pi5:ble": [-60, -62, -64]}
    lines = radio_node.summary(seen, {"east>pi5:ble": [8.0, 6.0, 9.0], "west>pi5:ble": []}, 3.0).splitlines()
    assert lines[0].split() == ["link", "n", "adverts/s", "lowest", "10s", "median", "10s", "median", "dBm"]
    assert lines[1].split() == ["east>pi5:ble", "3", "1.0", "6.0", "8.0", "-62.0"]
    assert lines[2].split() == ["west>pi5:ble", "0", "0.0", "__", "__", "__"]


def test_windows_get_one_rate_per_status_line(monkeypatch):
    monkeypatch.setattr(radio_node, "QUIET_S", 1000.0)
    fake = FakeController(events=[fixture("legacy_report_east")] * 5)
    windows = {}
    run(hci.Hci(fake), bus_sock=FlakySock(fail=0), stop=loops(20), clock=Clock(1.0), windows=windows,
        log=lambda line: None)
    # one rate per status line for every link Pi A hears (pi5b>pi5:ble too in the desk layout)
    assert windows == {link: ([0.5, 0.0] if link == "east>pi5:ble" else [0.0, 0.0]) for link in radio_node.PI_LINKS}


def test_timed_run_prints_the_summary(monkeypatch, capsys):
    fake = FakeController(events=[fixture("legacy_report_east"), fixture("legacy_reports_three")])
    monkeypatch.setattr(radio_node, "open_controller", lambda dev: hci.Hci(fake))
    monkeypatch.setattr(radio_node, "BUS_HOST", "127.0.0.1")
    radio_node.main(["--seconds", "0.2"])
    err = capsys.readouterr().err.splitlines()
    rows = {line.split()[0]: line.split() for line in err[-len(radio_node.PI_LINKS):]}
    assert err[-len(radio_node.PI_LINKS) - 1].split()[:5] == ["link", "n", "adverts/s", "lowest", "10s"]
    assert list(rows) == list(radio_node.PI_LINKS)
    assert rows["east>pi5:ble"][1] == "1" and rows["east>pi5:ble"][-1] == "-61.0"
    assert rows["west>pi5:ble"][1] == "1" and rows["west>pi5:ble"][-1] == "-70.0"


def test_status_line_says_which_beacon_and_the_interval_the_controller_took(monkeypatch):
    monkeypatch.setattr(radio_node, "QUIET_S", 1000.0)
    fake = FakeController(events=[fixture("legacy_report_east")] * 4)
    lines = []
    run(hci.Hci(fake), bus_sock=FlakySock(fail=0), stop=loops(10), clock=Clock(1.0), log=lines.append)
    status = [line for line in lines if "/s" in line]
    assert status and status[0].endswith("; set up again 0x since start; beacon S every 20 ms, connectable")


def test_status_line_shows_100_ms_when_the_controller_refuses_below_it(monkeypatch):
    monkeypatch.setattr(radio_node, "QUIET_S", 1000.0)
    fake = Floors({CONN: 0xA0, SCAN: 0xA0, NONCONN: 0xA0}, events=[fixture("legacy_report_east")] * 4)
    lines = []
    run(hci.Hci(fake), bus_sock=FlakySock(fail=0), stop=loops(10), clock=Clock(1.0), log=lines.append)
    assert any(line.endswith("beacon S every 100 ms, connectable") for line in lines if "/s" in line)


def test_no_scan_advertises_only_and_never_sets_up_again_for_silence():
    fake = FakeController()
    lines = []
    run(hci.Hci(fake), bus_sock=FlakySock(fail=0), stop=loops(30), clock=Clock(1.0), log=lines.append, scan=False)
    assert fake.sent.count(ADV_ON) == 1                       # silence is expected: no setup again
    assert hci.command_packet(*hci.scan_enable(False, True)) not in fake.sent   # the scan is never turned on
    assert not any("no adverts" in line for line in lines)
    assert any(line.endswith("beacon S every 20 ms, connectable, not scanning") for line in lines if "set up again" in line)


def test_no_scan_flag_reaches_the_run(monkeypatch):
    got = {}
    monkeypatch.setattr(radio_node, "open_controller", lambda dev: hci.Hci(FakeController()))
    monkeypatch.setattr(radio_node, "run", lambda dev, **kw: got.update(kw))
    radio_node.main(["--no-scan"])
    assert got["scan"] is False
    radio_node.main([])
    assert got["scan"] is True
