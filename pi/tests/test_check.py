"""pi.check against faked command output (no Bluetooth, systemd or network needed)."""
import re

import pytest

from pi import check

BTMGMT_ON = """Index list with 1 item
hci0:\tPrimary controller
\tsupported settings: powered connectable fast-connectable discoverable bondable le advertising
\tcurrent settings: powered bondable ssp br/edr le secure-conn
"""
STATUS = ("[pi.radio_node] advertising beacon S, scanning on hci0; forwarding to 192.168.77.2:5600\n"
          "[pi.radio_node] east>pi5:ble {e}/s, west>pi5:ble {w}/s; sent {s}, not sent {f}{why}; "
          "set up again 0x since start\n")

HEALTHY = {
    "btmgmt info": (0, BTMGMT_ON),
    "systemctl is-active radio-sight-radio-node": (0, "active\n"),
    "journalctl -u radio-sight-radio-node --since -30s -o cat --no-pager":
        (0, STATUS.format(e="21.3", w="19.8", s="411", f="0", why="")),
    "ip -4 -o addr show dev eth0": (0, "2: eth0    inet 192.168.77.1/24 brd 192.168.77.255 scope global eth0\n"),
    "ping -c 1 -W 1 192.168.77.2": (0, ""),
    "nmcli -t -f NAME,DEVICE connection show --active": (0, "deadzone-ap:wlan0\ndeadzone-eth:eth0\nlo:lo\n"),
    "cat /proc/sys/net/ipv4/ip_forward": (0, "1\n"),
    "ip -4 -o addr show dev wlan0": (0, "3: wlan0    inet 10.42.0.1/24 brd 10.42.0.255 scope global wlan0\n"),
}


JOURNAL = "journalctl -u radio-sight-radio-node --since -30s -o cat --no-pager"


def fake(changes=None):
    table = {**HEALTHY, **(changes or {})}

    def run(*cmd):
        return table.get(" ".join(cmd), (1, ""))
    return run


def report(capsys, run):
    code = check.main(run)
    return code, capsys.readouterr().out


def test_all_ok(capsys):
    code, out = report(capsys, fake())
    assert code == 0
    assert out.splitlines()[-1] == "all ok"
    assert "ok    radio node: east>pi5:ble 21.3/s, west>pi5:ble 19.8/s, not sent 0" in out


def test_prints_no_device_address(capsys):
    _, out = report(capsys, fake())
    addresses = set(re.findall(r"\d+\.\d+\.\d+\.\d+", out))
    assert addresses <= {"192.168.77.1", "192.168.77.2", "10.42.0.1"}
    assert not re.search(r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", out)


@pytest.mark.parametrize("key, value, line, fix", [
    ("btmgmt info", (0, BTMGMT_ON.replace("current settings: powered ", "current settings: ")),
     "Bluetooth: hci0 missing or not powered", "bluetoothctl power on"),
    ("systemctl is-active radio-sight-radio-node", (3, "failed\n"),
     "radio-sight-radio-node is failed", "sudo bash pi/install.sh"),
    ("journalctl -u radio-sight-radio-node --since -30s -o cat --no-pager", (0, ""),
     "no status line in the last 30 s", "run this check with sudo"),
    ("ip -4 -o addr show dev eth0", (0, ""), "eth0 doesn't have 192.168.77.1/24", "sudo bash pi/eth.sh"),
    ("ping -c 1 -W 1 192.168.77.2", (1, ""), "the board (192.168.77.2) doesn't answer", "board/eth.sh"),
    ("nmcli -t -f NAME,DEVICE connection show --active", (0, "deadzone-eth:eth0\n"),
     "deadzone-ap profile isn't active", "sudo bash pi/ap.sh"),
    ("ip -4 -o addr show dev wlan0", (0, ""), "wlan0 doesn't have 10.42.0.1/24", "sudo bash pi/ap.sh"),
    ("cat /proc/sys/net/ipv4/ip_forward", (0, "0\n"), "forwarding: off", "nmcli connection up deadzone-ap"),
])
def test_each_failure_names_its_fix(capsys, key, value, line, fix):
    code, out = report(capsys, fake({key: value}))
    assert code == 1
    fail = next(i for i, text in enumerate(out.splitlines()) if text.startswith("FAIL"))
    assert line in out.splitlines()[fail]
    assert fix in out.splitlines()[fail + 1]


def test_sends_failing_points_at_ethernet(capsys):
    status = STATUS.format(e="20.0", w="20.0", s="0", f="57", why=" (Network is unreachable)")
    code, out = report(capsys, fake({JOURNAL: (0, status)}))
    assert code == 1
    assert "not sent 57 (Network is unreachable)" in out and "Ethernet link is down" in out


def test_a_silent_beacon_is_named(capsys):
    status = STATUS.format(e="20.0", w="0.0", s="200", f="0", why="")
    code, out = report(capsys, fake({JOURNAL: (0, status)}))
    assert code == 1
    assert "nothing heard from beacon W" in out


def test_uses_the_latest_status_line(capsys):
    old = STATUS.format(e="0.0", w="0.0", s="0", f="0", why="")
    new = STATUS.format(e="20.0", w="20.0", s="400", f="0", why="")
    code, _ = report(capsys, fake({JOURNAL: (0, old + new)}))
    assert code == 0


def test_missing_tool_is_a_fail_not_a_crash():
    code, out = check.run("no-such-tool-for-pi-check")
    assert code == 127 and "not installed" in out


DESK = ("[pi.radio_node] east>pi5:ble 21.0/s, west>pi5:ble 20.0/s, pi5b>pi5:ble {b}/s; sent 600, not sent 0; "
        "set up again 0x since start\n")


def test_pi_a_on_the_desk_layout_also_needs_pi_bs_beacon(capsys):
    # In the desk layout Pi A also hears beacon B; a silent one points at Pi B's own check.
    code, out = report(capsys, fake({JOURNAL: (0, DESK.format(b="31.0"))}))
    assert code == 0 and "pi5b>pi5:ble 31.0/s" in out
    code, out = report(capsys, fake({JOURNAL: (0, DESK.format(b="0.0"))}))
    assert code == 1 and "nothing heard on pi5b>pi5:ble" in out and "pi.check --node pi5b" in out
