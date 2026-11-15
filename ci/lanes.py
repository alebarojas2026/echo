"""Which lanes a tree has, and the shell steps that test each one.

A lane is a top-level folder with a test_*.py file anywhere under it, plus contracts, plus web
when web/package.json exists. Every step runs from the repo root unless it names a cwd.
"""

import json
import posixpath

SKIP_PARTS = {".git", "node_modules", "dist", "__pycache__", ".venv", "ci-out"}


def discover_lanes(paths, package_json=None):
    """Lanes for a tree, given its tracked file paths (posix, relative to the repo root)."""
    found = set()
    top_level = set()
    for path in paths:
        parts = path.split("/")
        if len(parts) < 2 or SKIP_PARTS.intersection(parts):
            continue
        top_level.add(parts[0])
        name = parts[-1]
        if name.startswith("test_") and name.endswith(".py"):
            found.add(parts[0])
    if "contracts" in top_level:
        found.add("contracts")
    found.discard("web")  # web is tested with npm below, whatever .py files it holds
    lanes = sorted(found)
    if "web/package.json" in paths or package_json is not None:
        lanes.append("web")
    return lanes


def python_steps(lane, paths):
    """pytest for the folder, as ci.yml and the lane READMEs run it (python -m pytest <lane>)."""
    steps = []
    req = posixpath.join(lane, "requirements.txt")
    if req in paths:
        steps.append({"name": "deps", "cmd": f"pip install -q --disable-pip-version-check -r {req}", "setup": True})
    steps.append({"name": "pytest", "kind": "pytest", "cmd": f"python -m pytest {lane} -q -rfE -p no:cacheprovider --durations=5"})
    if lane == "contracts":
        steps.append({"name": "fixtures", "cmd": "python -m contracts.check contracts/fixtures/valid*"})
    return steps


def web_steps(package_json):
    """npm ci, the typecheck script, vitest and vite build, as AGENTS.md lists them."""
    scripts = (json.loads(package_json) if package_json else {}).get("scripts", {})
    typecheck = "npm run -s typecheck" if "typecheck" in scripts else "npx tsc --noEmit"
    return [
        {"name": "npm ci", "cwd": "web", "cmd": "npm ci --prefer-offline --no-audit --no-fund", "setup": True},
        {"name": "tsc", "kind": "tsc", "cwd": "web", "cmd": typecheck},
        {"name": "vitest", "kind": "vitest", "cwd": "web", "cmd": "npx vitest run"},
        {"name": "vite build", "kind": "build", "cwd": "web", "cmd": "npx vite build"},
    ]


def lane_steps(lane, paths, package_json=None):
    if lane == "web":
        return web_steps(package_json)
    return python_steps(lane, paths)


def requirement_lines(files):
    """Every requirement line from a {path: text} map of requirements*.txt files, deduplicated, in order."""
    seen, out = set(), []
    for path in sorted(files):
        for raw in files[path].splitlines():
            line = raw.split("#", 1)[0].strip()
            if line and not line.startswith("-") and line not in seen:
                seen.add(line)
                out.append(line)
    return out
