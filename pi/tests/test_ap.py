"""pi/ap.sh against a fake nmcli, iw and dmesg, in a throwaway copy of the repo (so no .env is read)."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from board.tests.shell import BASH

REPO = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")

FAKE = """#!/usr/bin/env bash
echo "$(basename "$0") $*" >> "$FAKE_LOG"
name=$(basename "$0")
if [ "$name" = dmesg ]; then echo "${FAKE_DMESG:-}"; fi
if [ "$name $*" = "iw reg get" ]; then echo "global"; echo "country US: DFS-FCC"; fi
exit 0
"""


@pytest.fixture
def pi(tmp_path):
    repo = tmp_path / "repo"
    (repo / "pi").mkdir(parents=True)
    shutil.copy(REPO / "pi" / "ap.sh", repo / "pi" / "ap.sh")
    fakes = tmp_path / "bin"
    fakes.mkdir()
    for name in ("nmcli", "iw", "dmesg"):
        (fakes / name).write_text(FAKE, newline="\n")
        (fakes / name).chmod(0o755)
    return repo, fakes, tmp_path / "calls.log"


def ap(pi, **env_extra):
    repo, fakes, log = pi
    env = {k: v for k, v in os.environ.items() if not k.startswith("SENSING_")}
    env.update({"PATH": str(fakes) + os.pathsep + env["PATH"], "FAKE_LOG": str(log),
                "SENSING_SSID": "test-net", "SENSING_PSK": "test-passphrase", **env_extra})
    r = subprocess.run([BASH, "pi/ap.sh"], cwd=repo, env=env, capture_output=True, text=True)
    calls = log.read_text().splitlines() if log.exists() else []
    return r, calls


def added(calls):
    return next(c for c in calls if c.startswith("nmcli connection add")).split()


def test_hotspot_wins_wlan0_over_saved_client_profiles(pi):
    r, calls = ap(pi)
    assert r.returncode == 0, r.stdout + r.stderr
    args = added(calls)
    assert args[args.index("ifname") + 1] == "wlan0"  # the Pi 5's built-in Wi-Fi when .env doesn't say
    assert args[args.index("connection.autoconnect-priority") + 1] == "100"
    assert args[args.index("wifi.mode") + 1] == "ap"
    assert args[args.index("wifi.channel") + 1] == "36"
    assert args[args.index("ipv4.addresses") + 1] == "10.42.0.1/24"
    assert calls.index("nmcli connection delete deadzone-ap") < calls.index(" ".join(args))
    assert "nmcli connection up deadzone-ap" in calls


def test_sensing_iface_from_env(pi):
    _, calls = ap(pi, SENSING_IFACE="wlan1")
    args = added(calls)
    assert args[args.index("ifname") + 1] == "wlan1"


def test_missing_passphrase_stops_before_touching_anything(pi):
    r, calls = ap(pi, SENSING_PSK="")
    assert r.returncode != 0
    assert "SENSING_PSK" in r.stderr
    assert calls == []


def test_a_driver_error_after_start_fails(pi):
    r, _ = ap(pi, FAKE_DMESG="brcmfmac: brcmf_vif_set_mgmt_ie: vndr ie set error : -52")
    assert r.returncode == 1
    assert "brcmfmac error" in r.stderr
