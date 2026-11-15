"""pi.check --node pi5b (#460): Pi B has no cable and no hotspot of its own, so it checks its two
services and that it's joined to Pi A's hotspot with the board answering through Pi A."""
import pytest

from pi import check
from pi.tests.test_check import BTMGMT_ON

JOURNAL = "journalctl -u radio-sight-radio-node --since -30s -o cat --no-pager"
LINE = ("[pi.radio_node] pi5>pi5b:ble {s}/s, east>pi5b:ble {e}/s, west>pi5b:ble {w}/s; "
        "sent 600, not sent {f}{why}; set up again 0x since start\n")

PI_B = {
    "btmgmt info": (0, BTMGMT_ON),
    "systemctl is-active radio-sight-radio-node": (0, "active\n"),
    JOURNAL: (0, LINE.format(s="30.1", e="21.0", w="20.2", f="0", why="")),
    "systemctl is-active radio-sight-wifi-rssi": (0, "active\n"),
    "ip -4 -o addr show dev wlan0": (0, "3: wlan0    inet 10.42.0.57/24 brd 10.42.0.255 scope global wlan0\n"),
    "ping -c 1 -W 1 192.168.77.2": (0, ""),
}


def report(capsys, changes=None):
    table = {**PI_B, **(changes or {})}
    code = check.main(lambda *cmd: table.get(" ".join(cmd), (1, "")), node="pi5b")
    return code, capsys.readouterr().out


def test_pi_b_all_ok_without_cable_hotspot_or_forwarding(capsys):
    code, out = report(capsys)
    assert code == 0, out
    assert "pi5>pi5b:ble 30.1/s, east>pi5b:ble 21.0/s, west>pi5b:ble 20.2/s, not sent 0" in out
    assert "Ethernet" not in out and "forwarding" not in out


@pytest.mark.parametrize("changes, line, fix", [
    ({JOURNAL: (0, LINE.format(s="0.0", e="21.0", w="20.2", f="0", why=""))},
     "pi5>pi5b:ble 0.0/s", "nothing heard on pi5>pi5b:ble"),
    ({JOURNAL: (0, LINE.format(s="30.0", e="21.0", w="20.2", f="12", why=" (Network is unreachable)"))},
     "not sent 12 (Network is unreachable)", "through Pi A's hotspot"),
    ({"systemctl is-active radio-sight-wifi-rssi": (3, "failed\n")},
     "radio-sight-wifi-rssi is failed", "journalctl -u radio-sight-wifi-rssi"),
    ({"ip -4 -o addr show dev wlan0": (0, "")}, "isn't joined to Pi A's hotspot", "radio/wifi_join.sh"),
    ({"ip -4 -o addr show dev wlan0": (0, "3: wlan0    inet 10.42.0.1/24 scope global wlan0\n")},
     "isn't joined to Pi A's hotspot", "radio/wifi_join.sh"),
    ({"ping -c 1 -W 1 192.168.77.2": (1, "")}, "doesn't answer through Pi A", "on Pi A: python3 -m pi.check"),
])
def test_pi_b_failures_name_their_fix(capsys, changes, line, fix):
    code, out = report(capsys, changes)
    assert code == 1
    lines = out.splitlines()
    fail = next(i for i, text in enumerate(lines) if text.startswith("FAIL"))
    assert line in lines[fail] and fix in lines[fail + 1]


def test_node_comes_from_radio_node_in_env(monkeypatch, capsys):
    monkeypatch.setenv("RADIO_NODE", "pi5b")
    table = dict(PI_B)
    code = check.main(lambda *cmd: table.get(" ".join(cmd), (1, "")))
    assert code == 0, capsys.readouterr().out
