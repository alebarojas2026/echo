"""board/egress.sh with nft replaced by a fake that keeps its state in files."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

FAKE_NFT = r"""#!/bin/sh
state="$(dirname "$0")/state"
mkdir -p "$state"
case "$*" in
    "-f -")
        cat > "$state/ruleset"; touch "$state/table" ;;
    "list counter inet radio_sight_egress "*)
        [ -f "$state/table" ] || { echo "Error: No such file or directory" >&2; exit 1; }
        name=$5
        printf 'table inet radio_sight_egress {\n\tcounter %s {\n\t\tpackets 3 bytes %s\n\t}\n}\n' \
            "$name" "$(cat "$state/$name" 2>/dev/null || echo 0)" ;;
    "delete table inet radio_sight_egress")
        rm -f "$state/table" ;;
    *)
        echo "fake nft: unexpected $*" >&2; exit 1 ;;
esac
"""


def find_bash():
    if os.name != "nt":
        return shutil.which("bash")
    # Git for Windows keeps bash in <Git>/bin; a bare "bash" may be the WSL launcher.
    git = shutil.which("git")
    for up in Path(git).resolve().parents[:3] if git else []:
        if (up / "bin" / "bash.exe").exists() and (up / "bin" / "git.exe").exists():
            return str(up / "bin" / "bash.exe")
    return None


BASH = find_bash()
pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")


@pytest.fixture
def nft(tmp_path):
    fake = tmp_path / "nft"
    fake.write_text(FAKE_NFT, newline="\n")
    fake.chmod(0o755)
    return tmp_path


def egress(nft_dir, *args):
    env = {**os.environ, "NFT": (nft_dir / "nft").as_posix()}
    return subprocess.run([BASH, "board/egress.sh", *args], cwd=REPO, env=env,
                          capture_output=True, text=True)


def set_bytes(nft_dir, link_local, other):
    (nft_dir / "state" / "link_local").write_text(str(link_local))
    (nft_dir / "state" / "other").write_text(str(other))


def test_start_loads_one_atomic_ruleset(nft):
    r = egress(nft, "start")
    assert r.returncode == 0, r.stderr
    rules = (nft / "state" / "ruleset").read_text().splitlines()
    # recreate in one batch, so starting again zeroes the counters
    assert rules[:3] == ["add table inet radio_sight_egress", "delete table inet radio_sight_egress",
                         "add table inet radio_sight_egress"]
    text = "\n".join(rules)
    assert "type filter hook postrouting priority 0; policy accept;" in text
    assert "ip daddr { 127.0.0.0/8, 192.168.77.0/24, 10.42.0.0/24 } return" in text
    for ifname in ("lo", "docker*", "br-*", "veth*"):
        assert f'oifname "{ifname}" return' in text
    assert rules[-1] == 'add rule inet radio_sight_egress postrouting counter name "other"'


def test_local_networks_are_skipped_before_anything_is_counted(nft):
    egress(nft, "start")
    rules = (nft / "state" / "ruleset").read_text().splitlines()
    first_count = next(i for i, r in enumerate(rules) if "counter name" in r)
    skips = [i for i, r in enumerate(rules) if r.endswith(" return") and "counter" not in r]
    assert skips and max(skips) < first_count


def test_count_prints_the_bare_total(nft):
    egress(nft, "start")
    set_bytes(nft, 120, 0)
    r = egress(nft)
    assert r.returncode == 0 and r.stdout == "120\n"
    assert "120 link-local, 0 other" in r.stderr


def test_zero_is_zero(nft):
    egress(nft, "start")
    r = egress(nft, "count")
    assert r.stdout == "0\n"


def test_sums_both_counters(nft):
    egress(nft, "start")
    set_bytes(nft, 300, 4521)
    assert egress(nft).stdout == "4821\n"


def test_not_started_fails_with_a_hint(nft):
    r = egress(nft)
    assert r.returncode == 1 and r.stdout == ""
    assert "egress.sh start" in r.stderr


def test_stop_prints_the_last_count_then_removes_the_table(nft):
    egress(nft, "start")
    set_bytes(nft, 0, 64)
    r = egress(nft, "stop")
    assert r.returncode == 0 and r.stdout == "64\n"
    assert not (nft / "state" / "table").exists()
    assert egress(nft).returncode == 1


def test_unknown_command_shows_usage(nft):
    r = egress(nft, "reset")
    assert r.returncode == 2 and "usage" in r.stderr
