"""board/push-web.sh with fake npm and ssh. The fake ssh runs the board's side
locally against a temporary "board" clone, so the copy and the swap are real."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from board.tests.shell import BASH, posix

REPO = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash and git")

FAKE_NPM = r"""#!/bin/sh
echo "npm $*" >> "$FAKE_LOG"
case "$1" in
    ci) mkdir -p node_modules && touch node_modules/.package-lock.json ;;
    run)
        [ -z "$FAKE_BUILD_FAIL" ] || exit 1
        rm -rf dist && mkdir -p dist/assets
        echo '<!doctype html><title>Radio Sight</title>' > dist/index.html
        echo 'console.log(1)' > dist/assets/app.js ;;
esac
"""

FAKE_SSH = r"""#!/bin/sh
jump=
if [ "$1" = "-J" ]; then jump=$2; shift 2; fi
host=$1; shift
echo "ssh jump=$jump host=$host cmd=$*" >> "$FAKE_LOG"
case "$host" in
    *@192.168.77.2|*@board-direct)
        [ -z "$FAKE_SSH_FAIL" ] || exit 255
        exec sh -c "$*" ;;
    *) exit "${FAKE_PI_EXIT:-0}" ;;
esac
"""


def git(repo, *args):
    return subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *args],
                          cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def setup(tmp_path):
    laptop = tmp_path / "laptop"
    (laptop / "board").mkdir(parents=True)
    shutil.copy(REPO / "board" / "push-web.sh", laptop / "board" / "push-web.sh")
    (laptop / "web" / "src").mkdir(parents=True)
    (laptop / "web" / "package.json").write_text("{}\n")
    (laptop / "web" / "package-lock.json").write_text("{}\n")
    (laptop / "web" / "src" / "main.ts").write_text("// v1\n")
    (laptop / ".gitignore").write_text(".env\nnode_modules/\ndist/\n")
    git(laptop, "init", "-q")
    git(laptop, "add", "-A")
    git(laptop, "commit", "-q", "-m", "first")

    board = tmp_path / "board-clone"
    (board / "web" / "dist").mkdir(parents=True)
    (board / "web" / "dist" / "old.js").write_text("stale\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, text in (("npm", FAKE_NPM), ("ssh", FAKE_SSH)):
        (bin_dir / name).write_text(text, newline="\n")
        (bin_dir / name).chmod(0o755)

    write_env(laptop, BOARD_USER="me", BOARD_REPO=posix(board), PI_USER="pi", PI_HOST="pi-host")
    return {"laptop": laptop, "board": board, "bin": bin_dir, "log": tmp_path / "log"}


def write_env(laptop, **values):
    # CRLF and quotes on purpose: .env files get edited on Windows too.
    lines = [f'{k}="{v}"' if k == "BOARD_USER" else f"{k}={v}" for k, v in values.items()]
    (laptop / ".env").write_text("# local settings\r\n" + "\r\n".join(lines) + "\r\n", newline="")


def push(s, ok=True, **env_extra):
    env = {k: v for k, v in os.environ.items()
           if k not in ("BOARD_USER", "BOARD_REPO", "BOARD_HOST", "PI_USER", "PI_HOST")}
    env.update(FAKE_BIN=posix(s["bin"]), FAKE_LOG=posix(s["log"]), **env_extra)
    # Prepend inside bash: Git's bash.exe puts its own /usr/bin first on startup.
    r = subprocess.run([BASH, "-c", 'PATH="$FAKE_BIN:$PATH" exec bash board/push-web.sh'],
                       cwd=s["laptop"], env=env, capture_output=True, text=True)
    assert (r.returncode == 0) == ok, r.stdout + r.stderr
    log = s["log"].read_text().splitlines() if s["log"].exists() else []
    return r.stdout + r.stderr, log


def test_copies_the_build_through_the_pi_and_swaps_it_in(setup):
    out, log = push(setup)
    dist = setup["board"] / "web" / "dist"
    sha = git(setup["laptop"], "rev-parse", "HEAD")
    assert (dist / "index.html").read_text().startswith("<!doctype html>")
    assert (dist / "assets" / "app.js").exists()
    assert (dist / "build.txt").read_text().strip() == sha
    assert not (dist / "old.js").exists()
    assert sorted(p.name for p in (setup["board"] / "web").iterdir()) == ["dist"]
    assert any(line.startswith("ssh jump=pi@pi-host host=me@192.168.77.2 ") for line in log)
    assert f"board is serving build {sha}" in out


def test_reopens_the_kiosk_on_the_pi(setup):
    out, log = push(setup)
    pi_calls = [line for line in log if "host=pi@pi-host" in line]
    assert len(pi_calls) == 1 and "pkill -f 'user-data-dir=.*radio-sight-kios[k]'" in pi_calls[0]
    assert "kiosk reopening" in out


def test_kiosk_not_running_is_only_a_note(setup):
    out, _ = push(setup, FAKE_PI_EXIT="1")
    assert "reload it by hand" in out


def test_direct_to_the_board_without_a_pi(setup):
    write_env(setup["laptop"], BOARD_USER="me", BOARD_REPO=posix(setup["board"]), BOARD_HOST="board-direct")
    _, log = push(setup)
    ssh = [line for line in log if line.startswith("ssh")]
    assert len(ssh) == 1 and ssh[0].startswith("ssh jump= host=me@board-direct ")


def test_environment_overrides_env_file(setup):
    _, log = push(setup, BOARD_USER="other")
    assert any("host=other@192.168.77.2" in line for line in log)


def test_npm_ci_runs_only_when_the_lockfile_changed(setup):
    push(setup)
    setup["log"].unlink()
    _, log = push(setup)
    assert "npm ci" not in log and "npm run build" in log


def test_uncommitted_web_changes_are_stamped_dirty(setup):
    (setup["laptop"] / "web" / "src" / "main.ts").write_text("// local\n")
    out, _ = push(setup)
    assert (setup["board"] / "web" / "dist" / "build.txt").read_text().strip().endswith("-dirty")
    assert "uncommitted" in out


@pytest.mark.parametrize("missing, message", [("BOARD_USER", "set BOARD_USER"),
                                              ("BOARD_REPO", "set BOARD_REPO"),
                                              ("PI_USER", "set PI_USER")])
def test_missing_settings_stop_before_building(setup, missing, message):
    values = dict(BOARD_USER="me", BOARD_REPO=posix(setup["board"]), PI_USER="pi", PI_HOST="pi-host")
    del values[missing]
    write_env(setup["laptop"], **values)
    out, log = push(setup, ok=False)
    assert message in out and log == []


@pytest.mark.parametrize("path", ["relative/clone", "/has space/clone", "/x'; rm -rf /'"])
def test_unsafe_board_paths_are_refused(setup, path):
    out, log = push(setup, ok=False, BOARD_REPO=path)
    assert "BOARD_REPO must be" in out and log == []


def test_failed_build_copies_nothing(setup):
    _, log = push(setup, ok=False, FAKE_BUILD_FAIL="1")
    assert not any(line.startswith("ssh") for line in log)
    assert (setup["board"] / "web" / "dist" / "old.js").exists()


def test_failed_copy_leaves_the_old_build(setup):
    out, _ = push(setup, ok=False, FAKE_SSH_FAIL="1")
    assert "copy failed" in out
    assert (setup["board"] / "web" / "dist" / "old.js").exists()
