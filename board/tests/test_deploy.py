"""board/deploy.sh against a throwaway git repo, with systemctl replaced by echo."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BOARD_UNITS = {"radio-sight-bus", "radio-sight-wifi-rssi", "radio-sight-hci-scan",
               "radio-sight-camwatch", "radio-sight-brain", "radio-sight-serve",
               "radio-sight-llm", "radio-sight-narrate"}


def find_bash():
    if os.name != "nt":
        return shutil.which("bash")
    # Git for Windows keeps bash in <Git>/bin, with git in <Git>/cmd or <Git>/mingw64/bin.
    # A bare "bash" on Windows may be the WSL launcher, so don't use that.
    git = shutil.which("git")
    for up in Path(git).resolve().parents[:3] if git else []:
        if (up / "bin" / "bash.exe").exists() and (up / "bin" / "git.exe").exists():
            return str(up / "bin" / "bash.exe")
    return None


BASH = find_bash()
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
    for path in ("board/serve.py", "bus/core.py", "radio/wifi_rssi.py", "radio/hci_scan.py",
                 "teacher/camwatch.py", "brain/main.py", "advisor/advice.py", "narrator/narrate.py",
                 "pi/radio_node.py", "web/src/main.ts", "docs/notes.md"):
        write(r, path, "# v1\n")
    write(r, "narrator/llm.service", "[Service]\nWorkingDirectory=@REPO@\nExecStart=/usr/bin/llama-server\n")
    git(r, "init", "-q")
    commit(r, "first")
    git(r, "tag", "v1")
    (tmp_path / "units").mkdir()
    return r


def deploy(repo, ref, role="board", ok=True):
    unit_dir = (repo.parent / "units").as_posix()
    env = {**os.environ, "ROLE": role, "UNIT_DIR": unit_dir, "SYSTEMCTL": "echo systemctl", "SUDO": ""}
    r = subprocess.run([BASH, "board/deploy.sh", ref], cwd=repo, env=env, capture_output=True, text=True)
    assert (r.returncode == 0) == ok, r.stdout + r.stderr
    restarted = set()
    for line in r.stdout.splitlines():
        if line.startswith("systemctl restart "):
            restarted |= {u.removesuffix(".service") for u in line.split()[2:]}
    return restarted, r.stdout + r.stderr


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


def test_same_ref_restarts_nothing(repo):
    deploy(repo, "v1")
    restarted, out = deploy(repo, "v1")
    assert restarted == set() and "nothing to restart" in out


@pytest.mark.parametrize("path, expected", [
    ("bus/core.py", {"radio-sight-bus"}),
    ("radio/hci_scan.py", {"radio-sight-wifi-rssi", "radio-sight-hci-scan"}),
    ("radio/nodes.json", {"radio-sight-wifi-rssi", "radio-sight-hci-scan", "radio-sight-brain"}),
    ("advisor/advice.py", {"radio-sight-brain"}),
    ("board/serve.py", {"radio-sight-serve"}),
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


def test_web_change_without_node_modules_warns(repo):
    deploy(repo, "v1")
    write(repo, "web/src/main.ts", "// v2\n")
    sha = commit(repo)
    git(repo, "checkout", "-q", "v1")
    restarted, out = deploy(repo, sha)
    assert restarted == set() and "web/dist is stale" in out


def test_missing_unit_source_is_skipped(repo):
    (repo / "narrator" / "llm.service").unlink()
    commit(repo)
    restarted, out = deploy(repo, "HEAD")
    assert "radio-sight-llm" not in restarted and "skipping radio-sight-llm" in out
