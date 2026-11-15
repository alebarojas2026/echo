"""Pin the code under test: agent/ and store/ (#474, now on main), nodes.json from the desk layout.

    python -m lab.ask_bench.overlay [--agent origin/main] [--nodes origin/layout-desk]

Files go to lab/ask_bench/.overlay/ (git-ignored) with the commit ids in pins.json, so a
score always names the exact code it came from. Nothing is copied into this branch.
"""
import argparse
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
OVERLAY = HERE / ".overlay"
AGENT_REF, NODES_REF = "origin/main", "origin/layout-desk"   # #474 merged to main
FILES = ("agent/__init__.py", "agent/ask.py", "agent/tools.py", "store/__init__.py", "store/__main__.py")


def git(*args) -> str:
    return subprocess.run(["git", *args], cwd=REPO, check=True, capture_output=True, text=True).stdout


def fetch(agent_ref: str = AGENT_REF, nodes_ref: str = NODES_REF, out: Path = OVERLAY) -> dict:
    for ref in {agent_ref, nodes_ref}:
        if ref.startswith("origin/"):
            git("fetch", "-q", "origin", ref.split("/", 1)[1])
    pairs = [(agent_ref, f) for f in FILES] + [(nodes_ref, "radio/nodes.json")]
    for ref, path in pairs:
        dest = out / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(git("show", f"{ref}:{path}"), encoding="utf-8")
    pins = {"agent": {"ref": agent_ref, "commit": git("rev-parse", agent_ref).strip()},
            "nodes": {"ref": nodes_ref, "commit": git("rev-parse", nodes_ref).strip()}}
    (out / "pins.json").write_text(json.dumps(pins, indent=1), encoding="utf-8")
    return pins


def use(out: Path = OVERLAY) -> dict:
    """Put the overlay first on sys.path and return the pins. Call before importing agent or store."""
    import sys
    if not (out / "pins.json").exists():
        raise SystemExit("run `python -m lab.ask_bench.overlay` first")
    if str(out) not in sys.path:
        sys.path.insert(0, str(out))
    return json.loads((out / "pins.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--agent", default=AGENT_REF)
    ap.add_argument("--nodes", default=NODES_REF)
    a = ap.parse_args()
    print(json.dumps(fetch(a.agent, a.nodes), indent=1))
