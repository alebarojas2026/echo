"""The sealed record's soak on Modal containers (simulated, design time only).

    python lab/soak/chain_farm.py tree --round r5             # this working tree (gate layout active) as a tarball
    modal run --detach lab/soak/chain_farm.py --round r5 --jobs "day:--hours 8,kill:--rounds 80"
    modal volume get soak-farm /r5 lab/soak/farm-runs          # results

A job is mode:args for lab/soak/chain_day.py, or live:args for lab/soak/day.py (the whole stack at real
speed, with two stand-in witnesses). debian:trixie-slim, Debian's Python 3.13 and openssl, like the board.
Timings on x86 containers say nothing about the board.
"""
import io
import json
import os
import shlex
import subprocess
import sys
import tarfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
TREES = HERE / "farm-trees"

try:
    import modal
except ImportError:
    modal = None


def cmd_tree(round_):
    buf = io.BytesIO()
    skip = {".git", "node_modules", "farm-trees", "farm-runs", "runs"}
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for p in sorted(REPO.rglob("*")):
            rel = p.relative_to(REPO)
            if p.is_file() and not (set(rel.parts) & skip) and not p.name.startswith("store.db"):
                tar.add(p, arcname=str(rel).replace("\\", "/"))
    (TREES / round_).mkdir(parents=True, exist_ok=True)
    (TREES / round_ / "kit5.tar.gz").write_bytes(buf.getvalue())
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    (TREES / round_ / "tree.json").write_text(json.dumps({"head": head, "bytes": len(buf.getvalue())}))
    print(head, len(buf.getvalue()))


if modal is not None:
    app = modal.App("soak-chain")
    vol = modal.Volume.from_name("soak-farm", create_if_missing=True)
    image = (modal.Image.from_registry("debian:trixie-slim")
             .apt_install("python3", "python3-pip", "python3-venv", "faketime", "procps", "sqlite3", "util-linux",
                          "openssl")
             .run_commands("ln -sf /usr/bin/python3 /usr/local/bin/python",
                           "python3 -m pip install --break-system-packages --no-cache-dir "
                           "numpy scikit-learn 'websockets>=14' psutil 'jsonschema>=4.18'"))

    def _job(tar_bytes: bytes, round_: str, name: str, mode: str, args: str) -> dict:
        import shutil
        import threading
        work = Path("/work/tree")
        work.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tar:
            tar.extractall(work)
        out, res = Path("/tmp/out") / name, Path("/vol") / round_ / name
        out.mkdir(parents=True, exist_ok=True)
        res.mkdir(parents=True, exist_ok=True)
        if mode == "live":
            ft = Path("/usr/lib/x86_64-linux-gnu/faketime/libfaketime.so.1").exists()
            argv = [sys.executable, "lab/soak/day.py", "--out", str(out), *shlex.split(args)] + (["--faketime"] if ft else [])
        else:
            argv = [sys.executable, "lab/soak/chain_day.py", mode, "--out", str(out), *shlex.split(args)]
        os.environ["SOAK_TREE"] = f"kit5 {round_}"
        log = open(out / "job.out", "w")
        p = subprocess.Popen(argv, cwd=work, stdout=log, stderr=subprocess.STDOUT)
        last = 0.0

        def sync():
            for f in out.rglob("*"):
                rel = f.relative_to(out)
                if f.is_file() and rel.parts[0] != "sessions" and not f.name.endswith((".db", ".db-wal", ".db-shm")):
                    dst = res / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(f, dst)
            for f in out.rglob("*.db"):
                (res / (f.name + ".size")).write_text(str(f.stat().st_size))
            vol.commit()
        while p.poll() is None:
            time.sleep(10)
            if time.time() - last > 120:
                last = time.time()
                sync()
        log.close()
        sync()
        try:
            return json.loads((out / "summary.json").read_text())
        except (OSError, ValueError):
            return {"error": "no summary", "exit": p.returncode, "tail": (out / "job.out").read_text()[-2000:]}

    @app.function(image=image, cpu=1.0, memory=2048, timeout=3 * 3600, volumes={"/vol": vol})
    def chain_job(*args):
        return _job(*args)

    @app.function(image=image, cpu=1.5, memory=3072, timeout=9 * 3600, volumes={"/vol": vol})
    def live_job(*args):
        return _job(*args)

    @app.local_entrypoint()
    def main(round: str, jobs: str):
        tar = (TREES / round / "kit5.tar.gz").read_bytes()
        calls = []
        for i, item in enumerate(jobs.split(",")):
            mode, _, args = item.partition(":")
            name = f"{mode}-{i}"
            fn = live_job if mode == "live" else chain_job
            calls.append((name, fn.spawn(tar, round, name, mode, args)))
            print("started", name, mode, args, flush=True)
        for name, c in calls:
            try:
                r = c.get()
                print(json.dumps({"job": name, "result": r}, default=str)[:4000], flush=True)
            except Exception as e:
                print(json.dumps({"job": name, "error": repr(e)}), flush=True)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "tree":
        cmd_tree(sys.argv[3] if sys.argv[2] == "--round" else sys.argv[2])
