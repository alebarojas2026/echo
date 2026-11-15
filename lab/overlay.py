"""Brain modules the lab needs that are still in open pull requests.

The lab runs the real brain code. Two pieces it needs are not on main yet, so
they are loaded from pinned PR commits, never copied into lab/:

    brain.core   PR #101  the live-loop state machine (gating, baseline, recording, training)
    brain.alert  PR #113  check-in and the no-movement alert

Once a file is on main (brain/core.py exists in the working tree), the normal
import wins and the pin is ignored. `python -m lab.overlay fetch` caches the
pinned sources in lab/.overlay/ (git-ignored) so Modal containers can use them.
"""
from __future__ import annotations

import importlib
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = Path(__file__).resolve().parent / ".overlay"

PINNED = {
    "brain.core": {"path": "brain/core.py", "pr": 101,
                   "commit": "92e0372522f22d6f6b0903366fa4e7a98a5e41d7"},
    "brain.alert": {"path": "brain/alert.py", "pr": 113,
                    "commit": "aae5805421cadf513c4a25cc2721eac62891a67f"},
}


def _cached(name: str) -> Path:
    return CACHE / (name.replace(".", "_") + ".py")


def fetch() -> None:
    """Cache every pinned file from git (fetching the PR head if needed)."""
    CACHE.mkdir(exist_ok=True)
    for name, pin in PINNED.items():
        if (ROOT / pin["path"]).exists():
            continue
        try:
            src = _git_show(pin)
        except subprocess.CalledProcessError:
            subprocess.run(["git", "fetch", "-q", "origin", f"pull/{pin['pr']}/head"],
                           cwd=ROOT, check=True)
            src = _git_show(pin)
        _cached(name).write_text(src, encoding="utf-8")


def _git_show(pin: dict) -> str:
    return subprocess.run(["git", "show", f"{pin['commit']}:{pin['path']}"], cwd=ROOT,
                          check=True, capture_output=True, text=True).stdout


def install() -> dict:
    """Make brain.core and brain.alert importable. Returns where each came from."""
    import brain
    used = {}
    for name, pin in PINNED.items():
        if name in sys.modules:
            used[name] = getattr(sys.modules[name], "__lab_source__", "main")
            continue
        if (ROOT / pin["path"]).exists():
            importlib.import_module(name)
            used[name] = "main"
            continue
        cached = _cached(name)
        if not cached.exists():
            fetch()
        mod = types.ModuleType(name)
        mod.__file__ = str(ROOT / pin["path"])   # so its relative paths (radio/nodes.json) resolve
        mod.__lab_source__ = f"PR #{pin['pr']} @ {pin['commit'][:7]}"
        sys.modules[name] = mod
        exec(compile(cached.read_text(encoding="utf-8"), str(cached), "exec"), mod.__dict__)
        setattr(brain, name.split(".")[1], mod)
        used[name] = mod.__lab_source__
    return used


if __name__ == "__main__":
    if sys.argv[1:] == ["fetch"]:
        fetch()
        print("\n".join(str(p) for p in sorted(CACHE.glob("*.py"))))
    else:
        print(install())
