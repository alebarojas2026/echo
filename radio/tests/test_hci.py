"""radio.hci and radio.hci_scan against hand-built HCI packets (fixtures/hci, from the Core spec)."""
import struct

import pytest

from radio import hci
from radio.hci_scan import BeaconScanner, kept, run, summary
from radio.tests.fakes import FIXTURES, FakeController, fixture


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.hex")), ids=lambda p: p.stem)
def test_fixture_length_byte_matches(path):
    packet = fixture(path.stem)
    assert packet[0] == hci.EVENT_PKT
    assert packet[2] == len(packet) - 3


@pytest.mark.parametrize("ext, on, expected", [
    (False, None, "01 0b 20 07 00 1000 1000 00 00"),               # passive, 10 ms / 10 ms, public, accept all
    (False, True, "01 0c 20 02 01 00"),                            # enable, Filter_Duplicates 0
    (False, False, "01 0c 20 02 00 00"),
    (True, None, "01 41 20 08 00 00 01 00 1000 1000"),             # own public, accept all, 1M only: passive 10/10 ms
    (True, True, "01 42 20 06 01 00 0000 0000"),                   # enable, Filter_Duplicates 0, no duration/period
    (True, False, "01 42 20 06 00 00 0000 0000"),
])
def test_scan_command_bytes(ext, on, expected):
    opcode, params = hci.scan_params(ext) if on is None else hci.scan_enable(ext, on)
    assert hci.command_packet(opcode, params) == bytes.fromhex(expected)


def test_event_filter_lets_through_command_results_and_le_meta():
    raw = hci.event_filter(hci.EV_CMD_COMPLETE, hci.EV_CMD_STATUS, hci.EV_LE_META)
    assert len(raw) == 16  # sizeof(struct hci_ufilter) with padding; newer kernels reject less
    assert struct.unpack("<IIIH2x", raw) == (1 << 4, (1 << 14) | (1 << 15), 1 << 30, 0)


def test_supported_commands_pick_the_scan_mode():
    for name, ext in [("read_supported_commands_ext", True), ("read_supported_commands_legacy", False)]:
        result = hci.command_result(fixture(name), hci.READ_LOCAL_SUPPORTED_COMMANDS)
        assert result[0] == 0 and len(result) == 65
        assert hci.supports(result[1:], hci.EXT_SCAN_ENABLE_BIT) is ext


def test_command_result_matches_only_its_opcode():
    packet = fixture("cmd_complete_scan_params_disallowed")
    assert hci.command_result(packet, hci.LE_SET_SCAN_PARAMS) == b"\x0c"
    assert hci.command_result(packet, hci.LE_SET_SCAN_ENABLE) is None
    assert hci.command_result(fixture("legacy_report_east"), hci.LE_SET_SCAN_PARAMS) is None
    status = bytes.fromhex("04 0f 04 00 01 0c 20")  # Command Status: success, 1 packet, 0x200C
    assert hci.command_result(status, hci.LE_SET_SCAN_ENABLE) == b"\x00"


def test_legacy_report_parsed_without_its_address():
    reports = list(hci.adv_reports(fixture("legacy_report_east")))
    assert reports == [(bytes.fromhex("020106 06ffffff525345"), -61)]
    assert list(hci.manufacturer_data(reports[0][0])) == [bytes.fromhex("ffff525345")]


@pytest.mark.parametrize("name, rx, expected", [
    ("legacy_report_east", "unoq", [("east>unoq:ble", -61)]),
    ("legacy_report_east", "pi5", [("east>pi5:ble", -61)]),
    ("legacy_reports_three", "unoq", [("west>unoq:ble", -70), ("pi5>unoq:ble", -80)]),
    ("legacy_reports_three", "pi5", [("west>pi5:ble", -70)]),        # the Pi never hears itself
    ("legacy_report_near_misses", "unoq", []),
    ("legacy_report_cut_short", "unoq", [("east>unoq:ble", -61)]),  # keeps what came before the cut
    ("ext_report_west", "unoq", [("west>unoq:ble", -56)]),
    ("ext_reports_two", "unoq", [("pi5>unoq:ble", -90)]),            # RSSI 127 = not available, dropped
    ("ext_reports_two", "pi5", []),
    ("read_supported_commands_ext", "unoq", []),
])
def test_only_our_beacons_are_kept(name, rx, expected):
    assert kept(fixture(name), rx) == expected


def test_near_misses_are_real_reports():
    # they are dropped by the beacon match, not by a parse failure
    assert len(list(hci.adv_reports(fixture("legacy_report_near_misses")))) == 5


@pytest.mark.parametrize("ext, params, enable", [
    (True, hci.LE_SET_EXT_SCAN_PARAMS, hci.LE_SET_EXT_SCAN_ENABLE),
    (False, hci.LE_SET_SCAN_PARAMS, hci.LE_SET_SCAN_ENABLE),
])
def test_scanner_uses_one_command_family(ext, params, enable):
    fake = FakeController(ext=ext)
    scanner = BeaconScanner(hci.Hci(fake), "unoq")
    scanner.start()
    scanner.stop()
    assert scanner.mode == ("extended" if ext else "legacy")
    # off (params can't change while on), params, on ... off; never a command from the other family
    assert fake.opcodes == [hci.READ_LOCAL_SUPPORTED_COMMANDS, enable, params, enable, enable]
    on = fake.sent[3]
    assert on[4] == 0x01 and on[5] == 0x00  # Enable 1, Filter_Duplicates 0


def test_run_sends_each_kept_report_and_turns_the_scan_off():
    events = [fixture("legacy_report_east"), fixture("cmd_complete_scan_params_disallowed"),
              fixture("legacy_reports_three"), fixture("legacy_report_near_misses")]
    fake = FakeController(events=events)
    sent = []
    seen = run(BeaconScanner(hci.Hci(fake), "unoq"), lambda *r: sent.append(r), stop=lambda: fake.drained)
    assert sent == [("east>unoq:ble", -61), ("west>unoq:ble", -70), ("pi5>unoq:ble", -80)]
    assert seen == {"east>unoq:ble": [-61], "west>unoq:ble": [-70], "pi5>unoq:ble": [-80]}
    assert fake.sent[-1] == hci.command_packet(*hci.scan_enable(False, False))


def test_ctrl_c_keeps_readings_and_turns_the_scan_off():
    fake = FakeController(events=[fixture("ext_report_west")], ext=True, at_end=KeyboardInterrupt)
    seen = {}
    with pytest.raises(KeyboardInterrupt):
        run(BeaconScanner(hci.Hci(fake), "unoq"), lambda *r: None, seen=seen)
    assert seen == {"west>unoq:ble": [-56]}
    assert fake.sent[-1] == hci.command_packet(*hci.scan_enable(True, False))


def test_command_waits_past_other_traffic():
    noise = [fixture("legacy_report_east"), fixture("cmd_complete_scan_params_disallowed")]
    dev = hci.Hci(FakeController(noise=noise))
    assert dev.command(*hci.scan_enable(False, True)) == b"\x00"


def test_failed_command_names_the_status():
    dev = hci.Hci(FakeController(status={hci.LE_SET_SCAN_PARAMS: 0x0C}))
    with pytest.raises(hci.HciError, match="0x200B: status 0x0C Command Disallowed"):
        dev.command(*hci.scan_params(False))
    assert dev.command(*hci.scan_params(False), check=False) == b"\x0c"


def test_command_without_reply_times_out():
    class Silent(FakeController):
        def send(self, packet):
            self.sent.append(packet)

    with pytest.raises(hci.HciError, match="no reply"):
        hci.Hci(Silent()).command(*hci.scan_enable(False, True), timeout=0.05)


def test_summary_lists_rates_per_beacon_link_in_nodes_json_order():
    text = summary({"west>unoq:ble": [-50, -52], "east>unoq:ble": [-60, -62, -61, -70]}, seconds=2.0)
    lines = text.splitlines()
    assert lines[1].split() == ["east>unoq:ble", "4", "2.0", "-61.5"]
    assert lines[2].split() == ["west>unoq:ble", "2", "1.0", "-51.0"]
    assert len(lines) == 3
