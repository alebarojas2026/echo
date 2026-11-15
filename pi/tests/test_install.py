"""pi/install.sh in a throwaway git checkout, with systemctl replaced by echo and a fake python3."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from board.tests.shell import BASH

REPO = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash and git")

# Stands in for `python3 -m venv DIR` (makes DIR/bin/python) and `python3 -m pi.check` (all ok).
FAKE_PYTHON3 = r"""#!/usr/bin/env bash
echo "python3 $*" >> "$FAKE_LOG"
if [ "$1 $2" = "-m pi.check" ]; then echo "all ok"; exit 0; fi
mkdir -p "$3/bin" && printf '#!/bin/sh\n' > "$3/bin/python" && chmod +x "$3/bin/python"
"""

# nmcli knows a deadzone-ap profile (an SD card copied from Pi A); `ip` prints $FAKE_ADDR;
# wifi_join.sh is replaced by a line in the log.
FAKE_NMCLI = r"""#!/usr/bin/env bash
echo "nmcli $*" >> "$FAKE_LOG"
if [ "$*" = "-t -f NAME connection show" ]; then printf 'deadzone-ap\nWired\n'; fi
"""
FAKE_IP = r"""#!/usr/bin/env bash
printf '%s' "$FAKE_ADDR"
"""
FAKE_JOIN = r"""#!/usr/bin/env bash
echo "wifi_join" >> "$FAKE_LOG"
"""


def git(repo, *args):
    subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *args],
                   cwd=repo, check=True, capture_output=True)


@pytest.fixture
def pi(tmp_path):
    repo = tmp_path / "repo"
    (repo / "pi").mkdir(parents=True)
    (repo / "board").mkdir()
    shutil.copy(REPO / "pi" / "install.sh", repo / "pi" / "install.sh")
    shutil.copy(REPO / "board" / "deploy.sh", repo / "board" / "deploy.sh")
    shutil.copytree(REPO / "board" / "units", repo / "board" / "units")
    (repo / "pi" / "radio_node.py").write_text("# stub\n", newline="\n")
    (repo / "narrator").mkdir()
    (repo / "narrator" / "llm.service").write_text("[Service]\n", newline="\n")
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "first")
    fakes = tmp_path / "bin"
    fakes.mkdir()
    for name, text in (("python3", FAKE_PYTHON3), ("nmcli", FAKE_NMCLI), ("ip", FAKE_IP), ("join", FAKE_JOIN)):
        (fakes / name).write_text(text, newline="\n")
        (fakes / name).chmod(0o755)
    (tmp_path / "units").mkdir()
    return repo, tmp_path


def install(pi, *args, addr="", code=0):
    repo, tmp = pi
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHON", "ROLE", "RADIO_NODE", "WIFI_IFACE")}
    env.update(PATH=str(tmp / "bin") + os.pathsep + env["PATH"], FAKE_LOG=str(tmp / "calls.log"),
               VENV=(tmp / "venv").as_posix(), UNIT_DIR=(tmp / "units").as_posix(),
               SYSTEMCTL="echo systemctl", SUDO="", NMCLI=(tmp / "bin" / "nmcli").as_posix(),
               IP=(tmp / "bin" / "ip").as_posix(), WIFI_JOIN=(tmp / "bin" / "join").as_posix(),
               FAKE_ADDR=addr, CHECK_WAIT_S="0")
    r = subprocess.run([BASH, "pi/install.sh", *args], cwd=repo, env=env, capture_output=True, text=True)
    assert r.returncode == code, r.stdout + r.stderr
    log = tmp / "calls.log"
    return r.stdout, (log.read_text().splitlines() if log.exists() else [])


def test_clean_checkout_one_command_installs_and_starts_the_node(pi):
    out, calls = install(pi)
    _, tmp = pi
    assert calls == [f"python3 -m venv {(tmp / 'venv').as_posix()}"]
    assert {p.stem for p in (tmp / "units").glob("*.service")} == {"radio-sight-radio-node"}
    unit = (tmp / "units" / "radio-sight-radio-node.service").read_text()
    assert f"ExecStart={(tmp / 'venv').as_posix()}/bin/python -m pi.radio_node" in unit
    assert "User=root" in unit and "Restart=always" in unit
    assert "systemctl enable --now --quiet radio-sight-radio-node.service" in out


def test_running_it_again_keeps_the_venv_and_restarts_nothing(pi):
    install(pi)
    out, calls = install(pi)
    assert len(calls) == 1  # the venv was made once
    assert "nothing to restart" in out
    assert "systemctl enable --now --quiet radio-sight-radio-node.service" in out


def test_pi_a_touches_no_env_and_no_hotspot(pi):
    repo, _ = pi
    _, calls = install(pi)
    assert not (repo / ".env").exists()
    assert not any(c.startswith(("nmcli", "wifi_join")) or "pi.check" in c for c in calls)


def test_pi_b_is_one_command_ending_in_its_check(pi):
    # #460: Pi B's .env lines, its own hotspot off, both units, the join, then pi.check's verdict.
    repo, tmp = pi
    out, calls = install(pi, "--node", "pi5b")
    env = (repo / ".env").read_text()
    assert env.splitlines() == ["RADIO_NODE='pi5b'", "WIFI_LINK='pi5>pi5b:wifi'", "BUS_HOST='192.168.77.2'"]
    assert "nmcli connection modify deadzone-ap connection.autoconnect no" in calls
    assert "nmcli connection down deadzone-ap" in calls
    assert {p.stem for p in (tmp / "units").glob("*.service")} == {"radio-sight-radio-node",
                                                                   "radio-sight-wifi-rssi"}
    assert calls[-2:] == ["wifi_join", "python3 -m pi.check --node pi5b"]
    assert out.rstrip().endswith("all ok")


def test_pi_b_again_keeps_the_env_and_an_existing_join(pi):
    repo, _ = pi
    (repo / ".env").write_text("SENSING_SSID=sensing\nBUS_HOST=192.168.77.2", newline="\n")
    out, calls = install(pi, "--node", "pi5b", addr="3: wlan0    inet 10.42.0.57/24 scope global wlan0\n")
    lines = (repo / ".env").read_text().splitlines()
    assert lines == ["SENSING_SSID=sensing", "BUS_HOST=192.168.77.2", "RADIO_NODE='pi5b'",
                     "WIFI_LINK='pi5>pi5b:wifi'"]
    assert ".env already sets BUS_HOST" in out
    assert "wifi_join" not in calls and "already on Pi A's hotspot" in out


def test_the_hotspots_own_address_is_not_a_join(pi):
    # 10.42.0.1 is the hotspot's own address: that Pi is serving it, not joined to it.
    _, calls = install(pi, "--node", "pi5b", addr="3: wlan0    inet 10.42.0.1/24 scope global wlan0\n")
    assert "wifi_join" in calls


def test_an_unknown_node_is_refused(pi):
    _, calls = install(pi, "--node", "east", code=2)
    assert calls == []
