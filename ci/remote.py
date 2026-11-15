"""The Modal side of ci/modal_ci.py: the image and the function that runs one lane of one tree.

This file imports only the standard library and modal, because it is the only file that is
loaded inside the container. modal_ci.py writes ci-out/.image/ (the requirement lines and the
web lockfile from origin/main) before it imports this module.
"""

import io
import json
import os
import shlex
import shutil
import subprocess
import tarfile
import time
from pathlib import Path

import modal

APP_NAME = "deadzone-ci"
LANE_TIMEOUT_S = 1200  # the whole container, image pull included
STEP_BUDGET_S = 1150  # what the steps of one lane may use together
OUTPUT_HEAD = 4_000
OUTPUT_TAIL = 30_000

TEST_USER = "ci"
IMAGE_DIR = Path(__file__).resolve().parent.parent / "ci-out" / ".image"

# Node 22 from nodejs.org, checked against the release's SHASUMS256.txt.
NODE_INSTALL = (
    "set -eu; base=https://nodejs.org/dist/latest-v22.x; cd /tmp; "
    "curl -fsSLO $base/SHASUMS256.txt; "
    "f=$(grep -o 'node-v22[^ ]*-linux-x64.tar.xz' SHASUMS256.txt | head -1); "
    "curl -fsSLO $base/$f; grep \" $f\\$\" SHASUMS256.txt | sha256sum -c -; "
    "tar -xJf $f -C /usr/local --strip-components=1 --exclude CHANGELOG.md --exclude LICENSE --exclude README.md; "
    "rm -f $f SHASUMS256.txt; node --version; npm --version"
)


def _image() -> modal.Image:
    image = modal.Image.from_registry(
        "debian:trixie-slim",
        setup_dockerfile_commands=[
            "RUN apt-get update && apt-get install -y --no-install-recommends "
            "python3 python3-pip python3-venv python-is-python3 git ca-certificates curl xz-utils "
            "&& rm -rf /var/lib/apt/lists/* && rm -f /usr/lib/python3*/EXTERNALLY-MANAGED "
            # Tests run as a normal login, like the board's services and a hosted runner, not as root.
            f"&& useradd -m -u 1000 {TEST_USER}",
        ],
    ).run_commands(NODE_INSTALL)
    if not modal.is_local():
        return image
    reqs_file = IMAGE_DIR / "requirements.txt"
    lines = reqs_file.read_text(encoding="utf-8").splitlines() if reqs_file.exists() else []
    # The test venv is separate from the python modal runs in, so it holds only what the repo asks for.
    pip = "/opt/ci/bin/pip install --no-cache-dir pytest " + " ".join(shlex.quote(x) for x in lines)
    image = image.run_commands(
        "python3 -m venv /opt/ci", pip, f"chown -R {TEST_USER}:{TEST_USER} /opt/ci", "/opt/ci/bin/pip list --format=freeze"
    ).env({"NPM_CONFIG_CACHE": "/opt/npm-cache"})
    lock = IMAGE_DIR / "web" / "package-lock.json"
    if lock.exists():
        # Warm npm's cache with main's lockfile; each lane still runs its own npm ci.
        image = (
            image.add_local_file(IMAGE_DIR / "web" / "package.json", "/opt/webwarm/package.json", copy=True)
            .add_local_file(lock, "/opt/webwarm/package-lock.json", copy=True)
            .run_commands(
                "cd /opt/webwarm && npm ci --no-audit --no-fund && rm -rf node_modules",
                f"chown -R {TEST_USER}:{TEST_USER} /opt/npm-cache",
            )
        )
    return image.env({"PATH": "/opt/ci/bin:/usr/local/bin:/usr/bin:/bin", "CI": "1", "NO_COLOR": "1"})


app = modal.App(APP_NAME)


def _clip(text: str) -> str:
    if len(text) <= OUTPUT_HEAD + OUTPUT_TAIL:
        return text
    return text[:OUTPUT_HEAD] + "\n[... cut ...]\n" + text[-OUTPUT_TAIL:]


# single_use_containers: every (tree, lane) gets a fresh container, so no files, /tmp or home
# folder are left over from another tree.
@app.function(image=_image(), cpu=2, memory=4096, timeout=LANE_TIMEOUT_S, max_containers=100, single_use_containers=True)
def run_lane(trees: modal.Dict, key: str, lane: str, steps: list) -> dict:
    """Unpack tree `key`, run the lane's steps in order, return each step's exit code and output.

    A step marked "setup" that fails stops the lane; every other step runs even if one failed.
    """
    started = time.monotonic()
    root = Path("/work/repo")
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(trees[key]), mode="r:gz") as tar:
        tar.extractall(root, filter="data")
    subprocess.run(["chown", "-R", f"{TEST_USER}:{TEST_USER}", "/work"], check=True)
    # A fresh login's environment: nothing of modal's own (its PYTHONPATH points at files the
    # test user can't read), only what the image sets.
    keep = ("PATH", "CI", "NO_COLOR", "NPM_CONFIG_CACHE")
    env = dict(
        {k: os.environ[k] for k in keep if k in os.environ},
        LANG="C.UTF-8",
        TERM="dumb",
        HOME=f"/home/{TEST_USER}",
        USER=TEST_USER,
        LOGNAME=TEST_USER,
        FORCE_COLOR="0",
        PYTHONDONTWRITEBYTECODE="1",
        NPM_CONFIG_UPDATE_NOTIFIER="false",
    )
    results = []
    for step in steps:
        left = STEP_BUDGET_S - (time.monotonic() - started)
        if left <= 5:
            results.append({"name": step["name"], "exit": None, "seconds": 0.0, "output": "not run: out of time"})
            break
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                ["bash", "-c", step["cmd"]],
                cwd=root / step.get("cwd", "."),
                env=env,
                user=TEST_USER,
                group=TEST_USER,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=left,
            )
            code, out = proc.returncode, proc.stdout.decode("utf-8", "replace")
        except subprocess.TimeoutExpired as exc:
            code = None
            out = (exc.output or b"").decode("utf-8", "replace") + f"\n[timed out after {left:.0f} s]"
        results.append({"name": step["name"], "exit": code, "seconds": round(time.monotonic() - t0, 1), "output": _clip(out)})
        if code != 0 and step.get("setup"):
            break
    versions = subprocess.run(
        ["bash", "-c", "python --version; node --version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    ).stdout.decode()
    return {"lane": lane, "key": key, "steps": results, "seconds": round(time.monotonic() - started, 1), "versions": versions.split()}


def run_all(jobs: list, tarballs: dict, on_result=None) -> list:
    """Run every (key, lane, steps) job in its own container. Returns results in job order."""
    out = []
    with modal.enable_output() if os.environ.get("CI_VERBOSE") else _nullcontext():
        with app.run():
            with modal.Dict.ephemeral() as trees:
                for key, blob in tarballs.items():
                    trees[key] = blob
                args = [(trees, key, lane, steps) for key, lane, steps in jobs]
                for res in run_lane.starmap(args, return_exceptions=True, order_outputs=True):
                    out.append(res)
                    if on_result:
                        on_result(res)
    return out


class _nullcontext:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


if __name__ == "__main__":  # pragma: no cover
    print(json.dumps({"app": APP_NAME, "timeout": LANE_TIMEOUT_S}))
