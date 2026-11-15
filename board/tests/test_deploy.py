"""board/deploy.sh against a throwaway git repo, with systemctl replaced by echo."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from board.tests.shell import BASH

REPO = Path(__file__).resolve().parents[2]
BOARD_UNITS = {"radio-sight-bus", "radio-sight-wifi-rssi", "radio-sight-hci-scan",
               "radio-sight-camwatch", "radio-sight-brain", "radio-sight-serve",
               "radio-sight-llm", "radio-sight-narrate", "radio-sight-store", "radio-sight-privacy"}
NEEDS_PI = {"radio-sight-wifi-rssi", "radio-sight-hci-scan"}


pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash and git")


def git(repo, *args):
    return subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *args],
                          cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def write(repo, path, text):
    f = repo / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, newline="\n")


def commit(repo, msg="change"):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    (r / "board").mkdir(parents=True)
    shutil.copy(REPO / "board" / "deploy.sh", r / "board" / "deploy.sh")
    shutil.copytree(REPO / "board" / "units", r / "board" / "units")
    for path in ("board/serve.py", "board/privacy.py", "board/privacy.nft", "store/__init__.py", "agent/endpoints.py", "bus/core.py", "radio/wifi_rssi.py", "radio/hci_scan.py",
                 "teacher/camwatch.py", "brain/main.py", "advisor/advice.py", "narrator/narrate.py",
                 "pi/radio_node.py", "web/src/main.ts", "docs/notes.md"):
        write(r, path, "# v1\n")
    write(r, ".gitignore", "dist/\n")
    write(r, "narrator/llm.service", "[Service]\nWorkingDirectory=@REPO@\nExecStart=/usr/bin/llama-server\n")
    git(r, "init", "-q")
    commit(r, "first")
    git(r, "tag", "v1")
    (tmp_path / "units").mkdir()
    return r


def deploy(repo, *args, role="board", ok=True, **env_extra):
    unit_dir = (repo.parent / "units").as_posix()
    env = {k: v for k, v in os.environ.items() if k != "PYTHON"}
    env.update(ROLE=role, UNIT_DIR=unit_dir, SYSTEMCTL="echo systemctl", SUDO="", **env_extra)
    r = subprocess.run([BASH, "board/deploy.sh", *args], cwd=repo, env=env, capture_output=True, text=True)
    assert (r.returncode == 0) == ok, r.stdout + r.stderr
    return calls(r.stdout, "restart"), r.stdout + r.stderr


def calls(out, verb):
    """Units passed to `systemctl <verb>` (flags dropped)."""
    units = set()
    for line in out.splitlines():
        if line.startswith(f"systemctl {verb} "):
            units |= {u.removesuffix(".service") for u in line.split()[2:] if not u.startswith("-")}
    return units


def installed(repo):
    return {p.stem for p in (repo.parent / "units").glob("*.service")}


def test_first_deploy_installs_and_starts_every_board_service(repo):
    restarted, out = deploy(repo, "v1")
    assert restarted == BOARD_UNITS
    assert installed(repo) == BOARD_UNITS
    assert "systemctl daemon-reload" in out and "systemctl enable" in out
    for unit in (repo.parent / "units").glob("*.service"):
        text = unit.read_text()
        assert "@REPO@" not in text and "@USER@" not in text and "@PYTHON@" not in text
        assert any(line.startswith("WorkingDirectory=/") and line.endswith("/repo")
                   for line in text.splitlines())


def test_units_run_as_root_only_where_the_contract_says(repo):
    deploy(repo, "v1")
    units = repo.parent / "units"
    roots = {u.stem for u in units.glob("*.service") if "User=root" in u.read_text()}
    assert roots == {"radio-sight-hci-scan"}
    assert all("Restart=always" in (units / f"{u}.service").read_text()
               for u in BOARD_UNITS - {"radio-sight-llm"})


def test_the_store_follows_the_brain_as_the_clone_owner(repo):
    deploy(repo, "v1")
    lines = (repo.parent / "units" / "radio-sight-store.service").read_text().splitlines()
    assert "After=radio-sight-brain.service" in lines and "Restart=always" in lines
    assert any(l.startswith("ExecStart=") and l.endswith(" -m store") for l in lines)
    assert any(l.startswith("User=") and l != "User=root" for l in lines)


def test_privacy_meter_gets_only_the_counter_privilege(repo):
    deploy(repo, "v1")
    lines = (repo.parent / "units" / "radio-sight-privacy.service").read_text().splitlines()
    assert any(l.startswith("User=") and l != "User=root" for l in lines)
    assert "AmbientCapabilities=CAP_NET_ADMIN" in lines and "CapabilityBoundingSet=CAP_NET_ADMIN" in lines
    assert "NoNewPrivileges=yes" in lines
    pre = [l for l in lines if l.startswith("ExecStartPre=")]
    assert len(pre) == 1 and pre[0].startswith("ExecStartPre=-+/usr/sbin/nft -f /")
    assert pre[0].endswith("/repo/board/privacy.nft")


def test_same_ref_restarts_nothing(repo):
    deploy(repo, "v1")
    restarted, out = deploy(repo, "v1")
    assert restarted == set() and "nothing to restart" in out


@pytest.mark.parametrize("path, expected", [
    ("bus/core.py", {"radio-sight-bus"}),
    ("radio/hci_scan.py", {"radio-sight-wifi-rssi", "radio-sight-hci-scan"}),
    ("radio/nodes.json", {"radio-sight-bus", "radio-sight-wifi-rssi", "radio-sight-hci-scan", "radio-sight-brain"}),
    ("advisor/advice.py", {"radio-sight-brain"}),
    ("board/serve.py", {"radio-sight-serve"}),
    ("store/__init__.py", {"radio-sight-store", "radio-sight-serve"}),
    ("agent/endpoints.py", {"radio-sight-serve"}),
    ("board/privacy.py", {"radio-sight-serve", "radio-sight-privacy"}),
    ("board/privacy.nft", {"radio-sight-privacy"}),
    ("narrator/narrate.py", {"radio-sight-narrate"}),
    ("narrator/llm.service", {"radio-sight-llm", "radio-sight-narrate"}),
    ("teacher/camwatch.py", {"radio-sight-camwatch"}),
    ("docs/notes.md", set()),
    ("pi/radio_node.py", set()),
])
def test_restarts_only_what_changed(repo, path, expected):
    deploy(repo, "v1")
    write(repo, path, "# v2\n")
    sha = commit(repo)
    git(repo, "checkout", "-q", "v1")
    restarted, _ = deploy(repo, sha)
    assert restarted == expected


def test_changed_unit_file_is_reinstalled_and_restarted(repo):
    deploy(repo, "v1")
    unit = repo / "board" / "units" / "radio-sight-serve.service"
    unit.write_text(unit.read_text().replace("RestartSec=2", "RestartSec=5"), newline="\n")
    sha = commit(repo)
    git(repo, "checkout", "-q", "v1")
    restarted, out = deploy(repo, sha)
    assert restarted == {"radio-sight-serve"} and "systemctl daemon-reload" in out
    assert "RestartSec=5" in (repo.parent / "units" / "radio-sight-serve.service").read_text()


def test_pi_gets_only_the_radio_node(repo):
    restarted, _ = deploy(repo, "v1", role="pi")
    assert restarted == installed(repo) == {"radio-sight-radio-node"}
    assert "User=root" in (repo.parent / "units" / "radio-sight-radio-node.service").read_text()


def test_refuses_uncommitted_changes(repo):
    write(repo, "bus/core.py", "# local edit\n")
    _, out = deploy(repo, "v1", ok=False)
    assert "uncommitted changes" in out


def test_unknown_ref_fails(repo):
    _, out = deploy(repo, "no-such-tag", ok=False)
    assert "unknown tag or sha" in out


def stamp(repo, built):
    (repo / "web" / "dist").mkdir(exist_ok=True)
    (repo / "web" / "dist" / "build.txt").write_text(built + "\n", newline="\n")


def test_no_web_build_says_how_to_push_one(repo):
    _, out = deploy(repo, "v1")
    assert "web/dist has no build.txt" in out and "board/push-web.sh" in out


def test_web_build_of_this_ref_is_current(repo):
    stamp(repo, git(repo, "rev-parse", "v1"))
    _, out = deploy(repo, "v1")
    assert "web/dist is current" in out


def test_web_build_stays_current_when_only_other_folders_change(repo):
    stamp(repo, git(repo, "rev-parse", "v1"))
    write(repo, "bus/core.py", "# v2\n")
    sha = commit(repo)
    git(repo, "checkout", "-q", "v1")
    _, out = deploy(repo, sha)
    assert "web/dist is current" in out


def test_web_change_makes_the_build_stale(repo):
    deploy(repo, "v1")
    stamp(repo, git(repo, "rev-parse", "v1"))
    write(repo, "web/src/main.ts", "// v2\n")
    sha = commit(repo)
    git(repo, "checkout", "-q", "v1")
    restarted, out = deploy(repo, sha)
    assert restarted == set() and "web/dist is stale" in out and "board/push-web.sh" in out


@pytest.mark.parametrize("built", ["{v1}-dirty", "0123456789abcdef0123456789abcdef01234567", "junk"])
def test_dirty_or_unknown_builds_are_stale(repo, built):
    stamp(repo, built.format(v1=git(repo, "rev-parse", "v1")))
    _, out = deploy(repo, "v1")
    assert "web/dist is stale" in out


def test_missing_unit_source_is_skipped(repo):
    (repo / "narrator" / "llm.service").unlink()
    commit(repo)
    restarted, out = deploy(repo, "HEAD")
    assert "radio-sight-llm" not in restarted and "skipping radio-sight-llm" in out


def test_every_run_enables_and_starts_every_unit(repo):
    deploy(repo, "v1")
    restarted, out = deploy(repo, "v1")
    assert restarted == set() and calls(out, "enable") == BOARD_UNITS


def test_install_uses_the_checkout_and_is_idempotent(repo):
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    restarted, out = deploy(repo, "--install")
    assert restarted == installed(repo) == calls(out, "enable") == BOARD_UNITS
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == branch  # nothing checked out
    restarted, out = deploy(repo, "--install")
    assert restarted == set() and calls(out, "enable") == BOARD_UNITS
    assert "systemctl daemon-reload" not in out


@pytest.mark.parametrize("args", [("--install", "--no-pi"), ("--no-pi", "v1")])
def test_no_pi_installs_everything_but_runs_only_what_works_alone(repo, args):
    restarted, out = deploy(repo, *args)
    assert installed(repo) == BOARD_UNITS
    assert calls(out, "enable") == BOARD_UNITS - NEEDS_PI
    assert calls(out, "disable") == NEEDS_PI
    assert restarted == BOARD_UNITS - NEEDS_PI


def test_dropping_no_pi_starts_the_pi_units(repo):
    deploy(repo, "--install", "--no-pi")
    restarted, out = deploy(repo, "--install")
    assert restarted == set() and calls(out, "enable") == BOARD_UNITS and calls(out, "disable") == set()


def test_pi_b_installs_its_node_and_its_wifi_reader(repo):
    # The desk layout's second Pi (#460): ROLE=pib, given by pi/install.sh.
    restarted, out = deploy(repo, "--install", role="pib")
    assert calls(out, "enable") == {"radio-sight-radio-node", "radio-sight-wifi-rssi"}
    assert restarted == {"radio-sight-radio-node", "radio-sight-wifi-rssi"}
    assert installed(repo) == {"radio-sight-radio-node", "radio-sight-wifi-rssi"}


def test_no_pi_on_the_pi_keeps_beacon_s_running(repo):
    # The radio node advertises and scans without the cable, so --no-pi must not stop it.
    restarted, out = deploy(repo, "--install", "--no-pi", role="pi")
    assert calls(out, "enable") == {"radio-sight-radio-node"}
    assert calls(out, "disable") == set()
    assert restarted == {"radio-sight-radio-node"}


def exec_start(repo, unit):
    text = (repo.parent / "units" / f"{unit}.service").read_text()
    return next(line for line in text.splitlines() if line.startswith("ExecStart="))


def test_python_defaults_to_the_board_venv(repo):
    _, out = deploy(repo, "--install")
    assert exec_start(repo, "radio-sight-bus") == "ExecStart=/opt/rs/venv/bin/python -m bus"


def test_python_can_be_overridden(repo):
    deploy(repo, "--install", PYTHON="/usr/local/bin/python3.11")
    assert exec_start(repo, "radio-sight-brain") == "ExecStart=/usr/local/bin/python3.11 -m brain.main"


def test_old_llm_service_is_removed(repo):
    old = repo.parent / "units" / "llm.service"
    old.write_text("[Unit]\nDescription=Radio Sight narrator model (llama-server on 127.0.0.1:8091)\n")
    _, out = deploy(repo, "--install")
    assert not old.exists() and "llm" in calls(out, "disable")
    assert "radio-sight-llm" in calls(out, "enable")


def test_someone_elses_llm_service_is_left_alone(repo):
    other = repo.parent / "units" / "llm.service"
    other.write_text("[Unit]\nDescription=something else\n")
    deploy(repo, "--install")
    assert other.exists()


@pytest.mark.parametrize("args", [(), ("--install", "v1"), ("--bogus",), ("v1", "v2")])
def test_bad_arguments_show_usage(repo, args):
    _, out = deploy(repo, *args, ok=False)
    assert "usage" in out or "unknown option" in out
