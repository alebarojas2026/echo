"""board/eth.sh with nmcli and ping replaced by fakes that log what they were asked."""
import os
import subprocess
from pathlib import Path

import pytest

from board.tests.shell import BASH

REPO = Path(__file__).resolve().parents[2]

# Answers `nmcli -t -f DEVICE,TYPE device` from the file "devices"; logs every call to "calls".
FAKE_NMCLI = r"""#!/bin/sh
dir="$(dirname "$0")"
echo "$*" >> "$dir/calls"
case "$1 $2 $3 $4" in
    "-t -f DEVICE,TYPE device") cat "$dir/devices" ;;
esac
case "$1 $2" in
    "connection up") [ ! -f "$dir/no_carrier" ] || exit 4 ;;
esac
exit 0
"""

pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")


@pytest.fixture
def fakes(tmp_path):
    for name, text in (("nmcli", FAKE_NMCLI), ("ping", "#!/bin/sh\nexit 0\n")):
        (tmp_path / name).write_text(text, newline="\n")
        (tmp_path / name).chmod(0o755)
    return tmp_path


def eth(fakes, devices, **env):
    (fakes / "devices").write_text("\n".join(devices) + "\n", newline="\n")
    base = {k: v for k, v in os.environ.items() if k != "BOARD_ETH_IFACE"}
    env = {**base, "NMCLI": (fakes / "nmcli").as_posix(), "PING": (fakes / "ping").as_posix(),
           "ENV_FILE": (fakes / "no.env").as_posix(), **env}
    r = subprocess.run([BASH, "board/eth.sh"], cwd=REPO, env=env, capture_output=True, text=True)
    calls = (fakes / "calls").read_text().splitlines() if (fakes / "calls").exists() else []
    return r, calls


BOARD = ["lo:loopback", "wlan0:wifi", "usb0:ethernet", "docker0:bridge", "veth1:ethernet", "hubport:ethernet"]


def test_gives_the_one_wired_port_the_contract_address(fakes):
    r, calls = eth(fakes, BOARD)
    assert r.returncode == 0, r.stderr
    add = next(c for c in calls if c.startswith("connection add"))
    assert "ifname hubport " in add
    for setting in ("ipv4.method manual", "ipv4.addresses 192.168.77.2/24", "ipv4.never-default yes",
                    "connection.autoconnect-priority 50", "autoconnect yes"):
        assert setting in add
    assert calls[-1] == "connection up deadzone-eth"
    assert "Pi 192.168.77.1 reachable" in r.stdout


def test_two_wired_ports_ask_for_the_name_and_change_nothing(fakes):
    r, calls = eth(fakes, BOARD + ["otherport:ethernet"])
    assert r.returncode == 1
    assert "BOARD_ETH_IFACE" in r.stderr
    assert not any(c.startswith("connection add") for c in calls)


def test_no_wired_port_says_to_plug_it_in(fakes):
    r, calls = eth(fakes, ["lo:loopback", "wlan0:wifi"])
    assert r.returncode == 1 and "plug" in r.stderr
    assert not any(c.startswith("connection add") for c in calls)


def test_the_named_port_wins(fakes):
    r, calls = eth(fakes, BOARD + ["otherport:ethernet"], BOARD_ETH_IFACE="otherport")
    assert r.returncode == 0, r.stderr
    assert "ifname otherport " in next(c for c in calls if c.startswith("connection add"))
    assert not any("DEVICE,TYPE" in c for c in calls)


def test_no_cable_keeps_the_profile_and_says_so(fakes):
    (fakes / "no_carrier").write_text("")
    r, calls = eth(fakes, BOARD)
    assert r.returncode == 1 and "cable" in r.stderr
    assert any(c.startswith("connection add") for c in calls)
