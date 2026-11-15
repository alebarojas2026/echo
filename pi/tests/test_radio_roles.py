"""The Pi radio node's advertising modes (connectable, and dropping what connects) and its roles
(beacon-only, listen-only, or from the links in nodes.json), against the fake controller."""
import socket
import struct

import pytest

from pi import radio_node
from pi.radio_node import (
    ADV_INTERVAL_HCI, HCI_DISCONNECT, LE_SET_ADV_ENABLE, LE_SET_ADV_PARAMS, READ_LOCAL_VERSION,
    build_adv_params_params, link_roles, roles, run,
)
from pi.tests.test_radio_node import CONN, NONCONN, SCAN, Clock, Floors, FlakySock, loops
from radio import hci
from radio.tests.fakes import FakeController, fixture

ADV_ON = hci.command_packet(LE_SET_ADV_ENABLE, b"\x01")
ADV_OFF = hci.command_packet(LE_SET_ADV_ENABLE, b"\x00")
SCAN_ON = hci.command_packet(*hci.scan_enable(False, True))


def connected(handle=0x0040, role=0x01, sub=0x01, status=0x00):
    """LE Connection Complete (or Enhanced, sub 0x0A / 0x29). role 1 = this controller is the peripheral.
    The peer address is all zeros: no real address is ever written down."""
    body = bytes([sub, status]) + struct.pack("<HB", handle, role) + bytes(1 + 6)
    if sub != 0x01:
        body += bytes(12)  # local and peer resolvable private addresses
    body += struct.pack("<HHH", 0x0018, 0, 0x01F4) + b"\x00"
    return bytes([hci.EVENT_PKT, hci.EV_LE_META, len(body)]) + body


def disconnection(handle=0x0040):
    return bytes([hci.EVENT_PKT, 0x05, 4, 0x00]) + struct.pack("<HB", handle, 0x13)


def disconnect_cmd(handle=0x0040):
    return hci.command_packet(HCI_DISCONNECT, struct.pack("<HB", handle, 0x13))


def quiet(monkeypatch):
    monkeypatch.setattr(radio_node, "QUIET_S", 1000.0)


# Which advert is tried first, and in what order

def test_connectable_params_differ_only_in_the_advertising_type():
    nonconn, conn = build_adv_params_params(), build_adv_params_params(ADV_INTERVAL_HCI, "connectable")
    assert conn[4] == 0x00 and nonconn[4] == 0x03       # ADV_IND, ADV_NONCONN_IND
    assert conn[:4] == nonconn[:4] == bytes.fromhex("20 00 20 00")
    assert conn[5:] == nonconn[5:]                       # same addresses, channels 37-39, filter policy


def test_the_ladder_and_its_units():
    assert [radio_node.units(ms) for ms in radio_node.LADDER_MS] == [32, 48, 64, 80, 96, 128, 160]
    assert radio_node.TYPE_ORDER == ("connectable", "scannable", "non-connectable")
    assert build_adv_params_params(32, "scannable")[4] == 0x02


class Version(FakeController):
    """Answers Read Local Version Information with HCI_Version `v`, and LE Read Local Supported
    Features with `features` (8 bytes)."""

    def __init__(self, v, features=bytes(8), **kw):
        super().__init__(**kw)
        self.v, self.features = v, features

    def send(self, packet):
        opcode = struct.unpack_from("<H", packet, 1)[0]
        if opcode == READ_LOCAL_VERSION:
            params = bytes([self.v, 0, 0, self.v, 0, 0, 0, 0])
        elif opcode == radio_node.LE_READ_LOCAL_FEATURES:
            params = self.features
        else:
            return super().send(packet)
        self.sent.append(bytes(packet))
        params = struct.pack("<HB", opcode, 0) + params
        self.replies.append(bytes([4, 0x0E, 1 + len(params), 1]) + params)


def test_what_the_controller_can_do_is_logged_once_at_start(monkeypatch):
    monkeypatch.setattr(radio_node, "SETTLE_S", 0.0)
    reset = bytes.fromhex("04 0e 04 01 03 0c 00")
    fake = Version(9, features=bytes([0xFF, 0x01, 0, 0, 0, 0, 0, 0]), events=[reset, fixture("legacy_report_east")])
    lines = []
    run(hci.Hci(fake), bus_sock=FlakySock(fail=0), stop=lambda: fake.drained, log=lines.append)
    told = [line for line in lines if line.startswith("[pi.radio_node] controller: ")]
    assert told == ["[pi.radio_node] controller: HCI version 9, extended advertising commands no, "
                    "extended scanning commands no, LE extended advertising feature no, LE features ff01000000000000"]


def test_extended_advertising_is_reported_when_the_controller_has_it():
    fake = Version(11, features=bytes([0, 0x10, 0, 0, 0, 0, 0, 0]), ext=True)
    line = radio_node.capabilities(hci.Hci(fake))
    assert "HCI version 11" in line and "extended scanning commands yes" in line
    assert "LE extended advertising feature yes" in line


def test_a_controller_that_says_little_is_logged_with_blanks():
    line = radio_node.capabilities(hci.Hci(FakeController()))
    assert line == ("[pi.radio_node] controller: HCI version __, extended advertising commands no, "
                    "extended scanning commands no, LE features __")


def test_setting_up_again_keeps_the_advert_it_got(monkeypatch):
    monkeypatch.setattr(radio_node, "SETTLE_S", 0.0)
    reset = bytes.fromhex("04 0e 04 01 03 0c 00")
    fake = Floors({CONN: 0x30, SCAN: None, NONCONN: None},
                  events=[fixture("legacy_report_east"), reset, fixture("legacy_report_east")])
    lines = []
    run(hci.Hci(fake), bus_sock=FlakySock(fail=0), stop=lambda: fake.drained, log=lines.append)
    assert fake.adverts == [(20, CONN), (30, CONN), (20, SCAN), (20, NONCONN), (30, CONN), (30, CONN)]
    assert sum("advertising every" in line for line in lines) == 1   # the ladder is walked once


def test_setting_up_again_walks_the_ladder_again_if_what_it_had_is_refused_now(monkeypatch):
    monkeypatch.setattr(radio_node, "SETTLE_S", 0.0)
    reset = bytes.fromhex("04 0e 04 01 03 0c 00")

    class Stricter(Floors):
        def recv(self, size):
            packet = super().recv(size)
            if packet == reset:
                self.floors = {CONN: None}
            return packet

    fake = Stricter(events=[reset, fixture("legacy_report_east")])
    run(hci.Hci(fake), bus_sock=FlakySock(fail=0), stop=lambda: fake.drained, log=lambda line: None)
    assert fake.adverts[-1] == (20, SCAN)


# Anything that connects to the connectable beacon is dropped, and the beacon starts again

def test_a_connection_is_dropped_at_once_and_the_beacon_starts_again(monkeypatch):
    quiet(monkeypatch)
    fake = FakeController(events=[fixture("legacy_report_east"), connected(), fixture("legacy_report_east")])
    lines, sock = [], FlakySock(fail=0)
    seen = run(hci.Hci(fake), bus_sock=sock, stop=loops(12), clock=Clock(1.0), seen={}, log=lines.append,
               adv_mode="connectable")
    i = fake.sent.index(disconnect_cmd())
    assert fake.sent[i + 1] == ADV_ON                    # advertising again straight after the drop
    assert fake.sent.count(ADV_ON) == 2
    assert any("something connected to beacon S" in line for line in lines)
    assert any("1 connection dropped since start" in line for line in lines if "/s" in line)
    assert seen == {"east>pi5:ble": [-61, -61]}          # scanning and sending went on
    assert len(sock.sent) == 2


@pytest.mark.parametrize("sub", [0x0A, 0x29], ids=["enhanced", "enhanced-v2"])
def test_an_enhanced_connection_complete_is_dropped_too(sub):
    fake = FakeController(events=[connected(handle=0x0002, sub=sub)])
    run(hci.Hci(fake), bus_sock=FlakySock(fail=0), stop=lambda: fake.drained, log=lambda line: None,
        adv_mode="connectable")
    assert disconnect_cmd(0x0002) in fake.sent


def test_a_connection_this_controller_made_itself_is_left_alone():
    fake = FakeController(events=[connected(role=0x00), connected(status=0x3E)])  # central; and a failed one
    run(hci.Hci(fake), bus_sock=FlakySock(fail=0), stop=lambda: fake.drained, log=lambda line: None,
        adv_mode="connectable")
    assert not any(struct.unpack_from("<H", p, 1)[0] == HCI_DISCONNECT for p in fake.sent)


def test_a_non_connectable_beacon_never_disconnects_anything():
    fake = FakeController(events=[connected()])
    run(hci.Hci(fake), bus_sock=FlakySock(fail=0), stop=lambda: fake.drained, log=lambda line: None,
        adv_mode="non-connectable")
    assert not any(struct.unpack_from("<H", p, 1)[0] == HCI_DISCONNECT for p in fake.sent)


class BusyWhileConnected(FakeController):
    """Won't advertise (0x0C Command Disallowed) between a Disconnect and its Disconnection Complete."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.connected = False

    def send(self, packet):
        opcode = struct.unpack_from("<H", packet, 1)[0]
        if opcode == HCI_DISCONNECT:
            self.connected = True
        self.status[LE_SET_ADV_ENABLE] = 0x0C if self.connected and packet == ADV_ON else 0
        super().send(packet)

    def recv(self, size):
        packet = super().recv(size)
        if packet == disconnection():
            self.connected = False
        return packet


def test_a_controller_that_waits_for_the_disconnection_advertises_after_it(monkeypatch):
    quiet(monkeypatch)
    fake = BusyWhileConnected(events=[connected(), disconnection()])
    run(hci.Hci(fake), bus_sock=FlakySock(fail=0), stop=lambda: fake.drained, log=lambda line: None,
        adv_mode="connectable")
    i = fake.sent.index(disconnect_cmd())
    after = [struct.unpack_from("<H", p, 1)[0] for p in fake.sent[i + 1:]]
    assert after[0] == LE_SET_ADV_ENABLE                          # tried at once: refused while connected
    assert after[1:5] == [LE_SET_ADV_ENABLE, LE_SET_ADV_PARAMS, radio_node.LE_SET_ADV_DATA, LE_SET_ADV_ENABLE]
    assert fake.sent[-1] == ADV_OFF                                # and turned off at the end, as always


def test_no_disconnection_complete_still_advertises_again_after_a_wait(monkeypatch):
    quiet(monkeypatch)

    class NeverSaysSo(BusyWhileConnected):
        def send(self, packet):
            super().send(packet)
            if packet == ADV_OFF:
                self.connected = False   # gone by the time the node sets up again

    fake = NeverSaysSo(events=[connected()])
    run(hci.Hci(fake), bus_sock=FlakySock(fail=0), stop=loops(6), clock=Clock(1.0), log=lambda line: None,
        adv_mode="connectable")
    i = fake.sent.index(disconnect_cmd())
    assert fake.sent[i + 1:].count(ADV_ON) == 2   # the refused try, then the setup REARM_WAIT_S later


def test_the_real_socket_also_hears_disconnection_complete():
    class Sock:
        def setsockopt(self, level, name, value):
            self.filter = value

    sock = Sock()
    radio_node.hear_disconnects(hci.Hci(sock))
    mask = struct.unpack_from("<II", sock.filter, 4)
    events = mask[0] | mask[1] << 32
    assert all(events >> ev & 1 for ev in (0x05, hci.EV_CMD_COMPLETE, hci.EV_CMD_STATUS, hci.EV_LE_META))


# Beacon-only and listen-only

def test_beacon_only_advertises_hears_nothing_sends_nothing_and_needs_no_network(monkeypatch):
    quiet(monkeypatch)

    def no_network(*args, **kw):
        raise AssertionError("a beacon-only node opens no socket")

    monkeypatch.setattr(radio_node.socket, "socket", no_network)
    fake = FakeController(events=[fixture("legacy_report_east")] * 3)
    lines = []
    seen = run(hci.Hci(fake), stop=loops(12), clock=Clock(1.0), seen={}, log=lines.append, scan=False)
    assert seen == {}
    assert SCAN_ON not in fake.sent and fake.sent.count(ADV_ON) == 1
    assert any(line == "[pi.radio_node] beacon only, nothing sent; set up again 0x since start; "
                       "beacon S every 20 ms, connectable, not scanning" for line in lines)


def test_listen_only_scans_and_sends_without_a_beacon(monkeypatch):
    quiet(monkeypatch)
    fake = FakeController(events=[fixture("legacy_report_east")] * 3)
    lines, sock = [], FlakySock(fail=0)
    run(hci.Hci(fake), bus_sock=sock, stop=loops(12), clock=Clock(1.0), log=lines.append, advertise=False)
    ops = fake.opcodes
    assert LE_SET_ADV_PARAMS not in ops and ADV_ON not in fake.sent and READ_LOCAL_VERSION not in ops
    assert fake.sent.index(ADV_OFF) < fake.sent.index(SCAN_ON)   # a beacon left on by an earlier run goes off
    assert [m["link"] for m in sock.sent] == ["east>pi5:ble"] * 3
    assert any(line.endswith("; not advertising") for line in lines if "/s" in line)


def test_a_reset_puts_back_only_what_the_role_has(monkeypatch):
    monkeypatch.setattr(radio_node, "SETTLE_S", 0.0)
    reset = bytes.fromhex("04 0e 04 01 03 0c 00")
    fake = FakeController(events=[reset, fixture("legacy_report_east")])
    run(hci.Hci(fake), bus_sock=FlakySock(fail=0), stop=lambda: fake.drained, log=lambda line: None, advertise=False)
    assert fake.sent.count(SCAN_ON) == 2 and ADV_ON not in fake.sent


# Roles from the links

GATE_LINKS = {link["id"]: link for link in (
    {"id": "pi5>unoq:wifi", "tx": "pi5", "rx": "unoq", "kind": "wifi"},
    {"id": "pi5b>unoq:ble", "tx": "pi5b", "rx": "unoq", "kind": "ble"},
    {"id": "pi5b>pi5:ble", "tx": "pi5b", "rx": "pi5", "kind": "ble"},
)}


def test_roles_follow_from_the_bluetooth_links():
    assert link_roles("pi5b", GATE_LINKS) == (True, False)    # tx in a link, rx in none: beacon-only
    assert link_roles("pi5", GATE_LINKS) == (False, True)     # a Wi-Fi tx is not a beacon: listen-only
    assert link_roles("pi5") == link_roles("pi5b") == (True, True)   # the desk layout: both, as before


def test_a_role_set_by_hand_wins_over_the_links():
    assert roles("pi5", "beacon-only", GATE_LINKS) == (True, False)
    assert roles("pi5b", "listen-only", GATE_LINKS) == (False, True)
    assert roles("pi5", "both", GATE_LINKS) == (True, True)
    assert roles("pi5", "auto", GATE_LINKS) == (False, True)


@pytest.fixture
def main_run(monkeypatch):
    got = {}
    monkeypatch.setattr(radio_node, "open_controller", lambda dev: hci.Hci(FakeController()))
    monkeypatch.setattr(radio_node, "run", lambda dev, **kw: got.update(kw))
    return got


@pytest.mark.parametrize("argv, advertise, scan", [
    ([], True, True),
    (["--beacon-only"], True, False),
    (["--no-scan"], True, False),
    (["--listen-only"], False, True),
    (["--role", "both"], True, True),
])
def test_role_flags_reach_the_run(main_run, argv, advertise, scan):
    radio_node.main(argv)
    assert (main_run["advertise"], main_run["scan"]) == (advertise, scan)


def test_radio_role_and_adv_mode_come_from_the_env(main_run, monkeypatch):
    monkeypatch.setattr(radio_node, "RADIO_ROLE", "beacon-only")
    monkeypatch.setattr(radio_node, "ADV_MODE", "connectable")
    radio_node.main(["--node", "pi5b"])
    assert (main_run["advertise"], main_run["scan"], main_run["adv_mode"], main_run["node"]) == \
        (True, False, "connectable", "pi5b")


def test_the_node_takes_its_role_from_the_layout(main_run, monkeypatch):
    monkeypatch.setattr(radio_node, "LINKS", GATE_LINKS)
    radio_node.main(["--node", "pi5b"])
    assert (main_run["advertise"], main_run["scan"]) == (True, False)
    radio_node.main(["--node", "pi5"])
    assert (main_run["advertise"], main_run["scan"]) == (False, True)


def test_a_node_in_no_bluetooth_link_says_so(main_run, monkeypatch):
    monkeypatch.setattr(radio_node, "LINKS", {"pi5>unoq:wifi": GATE_LINKS["pi5>unoq:wifi"]})
    with pytest.raises(SystemExit) as stopped:
        radio_node.main(["--node", "pi5b"])
    assert "nothing to do" in str(stopped.value.code)
    assert main_run == {}


@pytest.mark.parametrize("name, value", [("RADIO_ROLE", "beacon"), ("ADV_MODE", "fast")])
def test_a_bad_env_value_is_refused(main_run, monkeypatch, name, value):
    monkeypatch.setattr(radio_node, name, value)
    with pytest.raises(SystemExit) as stopped:
        radio_node.main([])
    assert stopped.value.code == 2 and main_run == {}


def test_beacon_only_timed_run_prints_no_summary(monkeypatch, capsys):
    monkeypatch.setattr(radio_node, "open_controller", lambda dev: hci.Hci(FakeController()))
    radio_node.main(["--beacon-only", "--seconds", "0.05"])
    err = capsys.readouterr().err
    assert "advertising beacon S, not scanning on hci0 (beacon-only); sending nothing, no network needed" in err
    assert "adverts/s" not in err
