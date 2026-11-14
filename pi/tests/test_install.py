"""pi/install.sh in a throwaway git checkout, with systemctl replaced by echo and a fake python3."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from board.tests.shell import BASH

REPO = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash and git")

# Stands in for `python3 -m venv DIR`: makes DIR/bin/python.
FAKE_PYTHON3 = """#!/usr/bin/env bash
echo "python3 $*" >> "$FAKE_LOG"
mkdir -p "$3/bin" && printf '#!/bin/sh\\n' > "$3/bin/python" && chmod +x "$3/bin/python"
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
    (fakes / "python3").write_text(FAKE_PYTHON3, newline="\n")
    (fakes / "python3").chmod(0o755)
    (tmp_path / "units").mkdir()
    return repo, tmp_path


def install(pi):
    repo, tmp = pi
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHON", "ROLE")}
    env.update(PATH=str(tmp / "bin") + os.pathsep + env["PATH"], FAKE_LOG=str(tmp / "calls.log"),
               VENV=(tmp / "venv").as_posix(), UNIT_DIR=(tmp / "units").as_posix(),
               SYSTEMCTL="echo systemctl", SUDO="")
    r = subprocess.run([BASH, "pi/install.sh"], cwd=repo, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
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
