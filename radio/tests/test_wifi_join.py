"""radio/wifi_join.sh with nmcli and iw replaced by fakes. No address-shaped text in this file."""
import os
import subprocess
from pathlib import Path

import pytest

from board.tests.shell import BASH

REPO = Path(__file__).resolve().parents[2]

FAKE_NMCLI = r"""#!/bin/sh
echo "$*" >> "$(dirname "$0")/calls"
exit 0
"""

# `iw dev <if> link` says it's joined to $JOINED_TO; `get power_save` says off.
FAKE_IW = r"""#!/bin/sh
case "$3" in
    link) echo "Connected to $JOINED_TO (on $2)" ;;
    get) echo "Power save: off" ;;
esac
"""

pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")


@pytest.fixture
def fakes(tmp_path):
    for name, text in (("nmcli", FAKE_NMCLI), ("iw", FAKE_IW)):
        (tmp_path / name).write_text(text, newline="\n")
        (tmp_path / name).chmod(0o755)
    (tmp_path / "env").write_text("SENSING_SSID=sensing\nSENSING_PSK=not-a-real-one\n"
                                  "SENSING_BSSID=PI-HOTSPOT\n", newline="\n")
    return tmp_path


def join(fakes, joined_to):
    keep = {k: v for k, v in os.environ.items() if not k.startswith(("SENSING_", "WIFI_"))}
    env = {**keep, "NMCLI": (fakes / "nmcli").as_posix(), "IW": (fakes / "iw").as_posix(),
           "ENV_FILE": (fakes / "env").as_posix(), "JOINED_TO": joined_to}
    r = subprocess.run([BASH, "radio/wifi_join.sh"], cwd=REPO, env=env, capture_output=True, text=True)
    return r, (fakes / "calls").read_text().splitlines()


def test_profile_is_locked_preferred_and_keeps_trying(fakes):
    r, calls = join(fakes, "pi-hotspot")   # iw prints lower case; the match ignores case
    assert r.returncode == 0, r.stderr
    add = next(c for c in calls if c.startswith("connection add"))
    for setting in ("ssid sensing", "802-11-wireless.bssid PI-HOTSPOT", "802-11-wireless.powersave 2",
                    "connection.autoconnect-priority 100", "connection.autoconnect-retries 0",
                    "ipv4.never-default yes", "ipv4.ignore-auto-dns yes", "802-11-wireless.band a"):
        assert setting in add
    assert calls[-1] == "connection up deadzone-sensing"
    assert "joined: wlan0 is on the Pi's hotspot" in r.stdout
    assert "Power save: off" in r.stdout


def test_joined_to_something_else_fails(fakes):
    r, _ = join(fakes, "phone-hotspot")
    assert r.returncode == 1
    assert "NOT joined" in r.stderr
    assert "PI-HOTSPOT" not in r.stdout + r.stderr   # the BSSID never goes in the output
