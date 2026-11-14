"""pi/eth.sh against a fake nmcli and ping, in a throwaway copy of the repo (so no .env is read)."""
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
case "$(basename "$0") $1 $2" in
    "nmcli connection up") exit "${FAKE_UP:-0}" ;;
    "ping -c 1") exit "${FAKE_PING:-0}" ;;
esac
exit 0
"""


@pytest.fixture
def pi(tmp_path):
    repo = tmp_path / "repo"
    (repo / "pi").mkdir(parents=True)
    shutil.copy(REPO / "pi" / "eth.sh", repo / "pi" / "eth.sh")
    fakes = tmp_path / "bin"
    fakes.mkdir()
    for name in ("nmcli", "ping"):
        (fakes / name).write_text(FAKE, newline="\n")
        (fakes / name).chmod(0o755)
    return repo, fakes, tmp_path / "calls.log"


def eth(pi, **env_extra):
    repo, fakes, log = pi
    env = {k: v for k, v in os.environ.items() if k != "ETH_IFACE"}
    env.update(PATH=str(fakes) + os.pathsep + env["PATH"], FAKE_LOG=str(log), **env_extra)
    r = subprocess.run([BASH, "pi/eth.sh"], cwd=repo, env=env, capture_output=True, text=True)
    calls = log.read_text().splitlines() if log.exists() else []
    return r, calls


def added(calls):
    return next(c for c in calls if c.startswith("nmcli connection add")).split()


def test_profile_wins_over_other_eth0_profiles_and_never_takes_the_default_route(pi):
    r, calls = eth(pi)
    assert r.returncode == 0, r.stdout + r.stderr
    args = added(calls)
    assert args[args.index("ifname") + 1] == "eth0"  # the Pi 5's port when .env doesn't say
    assert args[args.index("connection.autoconnect-priority") + 1] == "50"
    assert args[args.index("ipv4.addresses") + 1] == "192.168.77.1/24"
    assert args[args.index("ipv4.never-default") + 1] == "yes"
    assert calls[0] == "nmcli connection delete deadzone-eth"
    assert "nmcli connection up deadzone-eth" in calls
    assert "Board hub 192.168.77.2 reachable." in r.stdout


def test_eth_iface_from_env(pi):
    _, calls = eth(pi, ETH_IFACE="eth1")
    args = added(calls)
    assert args[args.index("ifname") + 1] == "eth1"


def test_no_cable_yet_is_not_a_failure(pi):
    r, calls = eth(pi, FAKE_UP="4")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "isn't up yet" in r.stdout and "comes up by itself" in r.stdout
    assert not any(c.startswith("ping") for c in calls)


def test_board_not_answering_yet_is_reported(pi):
    r, _ = eth(pi, FAKE_PING="1")
    assert r.returncode == 0
    assert "Board hub not yet reachable" in r.stdout
