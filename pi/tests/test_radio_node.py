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



# ---------------------------------------------------------------------------
# Failure paths: no Ethernet, the board not listening, the controller reset or gone
# ---------------------------------------------------------------------------

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
