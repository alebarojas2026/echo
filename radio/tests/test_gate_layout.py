"""The radio path on the gate layout: three devices, six links, no east, no west, no hall beacons.

Each check starts a fresh Python with RADIO_SIGHT_NODES naming radio/layouts/gate.json, so the
modules read that layout the way they read radio/nodes.json once it is switched.
"""
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "radio" / "layouts" / "gate.json"


def on_gate(code):
    """Runs `code` on the gate layout; it prints one JSON value, which is returned."""
    env = {**os.environ, "RADIO_SIGHT_NODES": str(GATE)}
    r = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_nodes_gives_six_links_two_beacons_and_no_hall():
    got = on_gate("import json; from radio import nodes as n; print(json.dumps("
                  "[list(n.LINKS), sorted(n.BEACONS.values()), n.RECEIVERS, n.PIS, list(n.HALL_LINKS), list(n.HEARD)]))")
    links = ["pi5>unoq:wifi", "pi5>unoq:ble", "pi5b>unoq:ble", "pi5>pi5b:wifi", "pi5>pi5b:ble", "pi5b>pi5:ble"]
    assert got == [links, ["pi5", "pi5b"], ["unoq", "pi5", "pi5b"], ["pi5", "pi5b"], [], links]


def test_each_scanner_keeps_only_the_pis_beacons():
    def report(letter):
        data = bytes([6, 0xFF, 0xFF, 0xFF, 0x52, 0x53, ord(letter)])
        return (bytes([0x04, 0x3E, 12 + len(data), 0x02, 1, 0x03, 0x01]) + bytes(6) + bytes([len(data)]) + data
                + struct.pack("b", -60)).hex()
    got = on_gate("import json; from radio import hci_scan as s; print(json.dumps("
                  f"[[s.kept(bytes.fromhex(p), rx) for p in {[report(c) for c in 'SBEWH']!r}] "
                  "for rx in ('unoq', 'pi5', 'pi5b')]))")
    assert got == [[[["pi5>unoq:ble", -60]], [["pi5b>unoq:ble", -60]], [], [], []],     # the board hears S and B
                   [[], [["pi5b>pi5:ble", -60]], [], [], []],                          # Pi A hears B, never itself
                   [[["pi5>pi5b:ble", -60]], [], [], [], []]]                          # Pi B hears S


def test_each_pi_listens_for_the_other_and_its_status_line_names_only_that():
    got = on_gate(
        "import json; from pi import radio_node as r\n"
        "bus = r.BusSender(None, ('127.0.0.1', 9))\n"
        "print(json.dumps([r.RADIO_NODES, r.heard_by('pi5'), r.heard_by('pi5b'), r.beacon_letter('pi5'), r.beacon_letter('pi5b'),"
        " r.status_line({'pi5b>pi5:ble': 55}, 10.0, bus, 0, r.heard_by('pi5'))]))")
    assert got[:5] == [["pi5", "pi5b"], ["pi5b>pi5:ble"], ["pi5>pi5b:ble"], "S", "B"]
    assert got[5].startswith("[pi.radio_node] pi5b>pi5:ble 5.5/s; sent 0, not sent 0")


def test_the_pi_check_passes_on_one_link_and_points_at_pi_b_when_it_is_silent():
    code = (
        "import json; from pi import check\n"
        "line = '[pi.radio_node] pi5b>pi5:ble %s/s; sent 60, not sent 0; set up again 0x since start'\n"
        "out = [check.radio_status(lambda *cmd: (0, line % rate)) for rate in ('5.8', '0.0')]\n"
        "print(json.dumps(out))")
    ok, silent = on_gate(code)
    assert ok == [True, "radio node: pi5b>pi5:ble 5.8/s, not sent 0", None]
    assert silent[0] is False and "nothing heard on pi5b>pi5:ble" in silent[2] and "pi.check --node pi5b" in silent[2]
    assert "beacon" not in silent[2]   # nothing asks for an E or W that isn't there


def test_gate_2_has_a_row_for_each_bluetooth_link_and_no_others():
    got = on_gate("import json; from radio import report_hci as h, check as c; print(json.dumps("
                  "[h.MIN_RATES, h.BEACON_OF, {k: c.gate_hz(k) for k in c.LINKS}]))")
    ble = ["pi5>unoq:ble", "pi5b>unoq:ble", "pi5>pi5b:ble", "pi5b>pi5:ble"]
    assert list(got[0]) == ble and set(got[0].values()) == {12.0}
    assert got[1] == {"pi5>unoq:ble": "S", "pi5b>unoq:ble": "B", "pi5>pi5b:ble": "S", "pi5b>pi5:ble": "B"}
    assert got[2]["pi5>unoq:wifi"] == got[2]["pi5>pi5b:wifi"] == 20.0 and len(got[2]) == 6


def test_the_wifi_reader_takes_either_wifi_link():
    got = on_gate("import json; from radio import wifi_rssi as w\n"
                  "out = []\n"
                  "for k in ('pi5>unoq:wifi', 'pi5>pi5b:wifi'):\n"
                  "    w.set_link(k); out.append([w.LINK_ID, w.TX, w.RX])\n"
                  "print(json.dumps(out))")
    assert got == [["pi5>unoq:wifi", "pi5", "unoq"], ["pi5>pi5b:wifi", "pi5", "pi5b"]]


def test_the_bus_lists_the_six_links():
    got = on_gate(f"import json; from bus import core; print(json.dumps(core.load_link_ids(r'{GATE}')))")
    assert len(got) == 6 and "east>unoq:ble" not in got
