"""The soak on many machines at once (simulated): seeded judging days on Modal containers.

    python lab/soak/farm.py trees --round r1 --prs 415,469,486,468,474,477,484
    modal run --detach lab/soak/farm.py --round r1 --plan "main:real:4:3,main:fast:8:1.5,heroes:real:4:3,heroes:fast:8:1.5"
    python lab/soak/farm.py fetch --round r1            # results to lab/soak/farm-runs/r1/
    python lab/soak/report.py lab/soak/farm-runs/r1

`trees` builds two trees on this PC, each with this branch's lab/soak/ copied in: "main" (origin/main)
and "heroes" (main plus every listed PR that merges cleanly; the ones that don't are listed in
trees.json). They go up as tarballs: no GitHub token leaves the PC.
Each plan item is tree:pace:containers:hours. A container runs lab/soak/day.py with its own seed on
debian:trixie-slim with Debian's Python 3.13 (like the board) and syncs its results to the
"soak-farm" volume every 5 minutes, so a container that dies still leaves what it saw.
Dev only, design time only: nothing here is needed at the demo. Timings on x86 say nothing about the board.
"""
import argparse
import io
import json
import os
import subprocess
import sys
import tarfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
TREES = HERE / "farm-trees"
LAB_FILES = ("soak.py", "day.py", "proxy.py", "fake_llm.py", "feeder.py", "gate.py")

try:
    import modal
except ImportError:   # `trees` and `fetch` work without it
    modal = None


def git(*args, cwd=REPO, check=True):
    return subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True)


def build_tree(name, prs, round_, base, layout=None):
    """A worktree of origin/main plus PRs, with lab/soak overlaid, as a tarball. Returns its record."""
    dest = TREES / round_ / name
    if dest.exists():
        git("worktree", "remove", "--force", str(dest), check=False)
    dest.parent.mkdir(parents=True, exist_ok=True)
    git("worktree", "add", "-q", "--detach", str(dest), base)
    merged, skipped = [], []
    for n in prs:
        r = git("merge", "-q", "--no-edit", "--no-ff", f"farm-pr{n}", cwd=dest, check=False)
        if r.returncode == 0:
            merged.append(n)
        else:
            git("merge", "--abort", cwd=dest, check=False)
            skipped.append(n)
    if layout:   # the layout the board runs: that file becomes radio/nodes.json, as on the board
        (dest / "radio" / "nodes.json").write_bytes((dest / layout).read_bytes())
    (dest / "lab" / "soak").mkdir(parents=True, exist_ok=True)
    for f in LAB_FILES:
        (dest / "lab" / "soak" / f).write_bytes((HERE / f).read_bytes())
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for p in sorted(dest.rglob("*")):
            rel = p.relative_to(dest)
            if p.is_file() and rel.parts[0] not in (".git", "node_modules") and "node_modules" not in rel.parts:
                tar.add(p, arcname=str(rel).replace("\\", "/"))
    (TREES / round_ / f"{name}.tar.gz").write_bytes(buf.getvalue())
    head = git("rev-parse", "HEAD", cwd=dest).stdout.strip()
    return {"tree": name, "layout": layout, "main": base, "head": head, "merged": merged, "skipped": skipped,
            "bytes": len(buf.getvalue())}


def cmd_trees(a):
    prs = [int(x) for x in a.prs.split(",") if x]
    git("fetch", "-q", "--force", "origin", "main", *[f"+pull/{n}/head:farm-pr{n}" for n in prs], check=False)
    base = git("rev-parse", "origin/main").stdout.strip()   # both trees on the same main
    hero_base = base
    if a.heroes_ref:   # the exact tree going onto the hardware, e.g. a deploy branch
        git("fetch", "-q", "--force", "origin", f"+{a.heroes_ref}:refs/remotes/origin/{a.heroes_ref}", check=False)
        hero_base = git("rev-parse", f"origin/{a.heroes_ref}").stdout.strip()
    if a.tree:   # name:prs:layout, e.g. kit:776,774:radio/layouts/gate.json
        git("fetch", "-q", "--force", "origin", *[f"+pull/{n}/head:farm-pr{n}" for t in a.tree
                                                 for n in t.split(":")[1].split(",") if n], check=False)
        out = [build_tree(t.split(":")[0], [int(n) for n in t.split(":")[1].split(",") if n], a.round, base,
                          t.split(":")[2] or None) for t in a.tree]
    else:
        out = [build_tree("main", [], a.round, base), build_tree("heroes", prs, a.round, hero_base)]
        out[1]["ref"] = a.heroes_ref or "main"
    (TREES / a.round / "trees.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


def cmd_fetch(a):
    dest = HERE / "farm-runs" / a.round
    dest.mkdir(parents=True, exist_ok=True)
    exe = Path(sys.executable).with_name("modal.exe" if os.name == "nt" else "modal")
    subprocess.run([str(exe), "volume", "get", "--force", "soak-farm", f"/{a.round}", str(dest.parent)], check=True)
    print("fetched to", dest)


if modal is not None:
    app = modal.App("soak-farm")
    vol = modal.Volume.from_name("soak-farm", create_if_missing=True)
    image = (modal.Image.from_registry("debian:trixie-slim")
             .apt_install("python3", "python3-pip", "python3-venv", "faketime", "procps", "sqlite3", "util-linux")
             .run_commands("ln -sf /usr/bin/python3 /usr/local/bin/python",
                           "python3 -m pip install --break-system-packages --no-cache-dir "
                           "numpy scikit-learn 'websockets>=14' psutil 'jsonschema>=4.18'"))

    def _day(tree_tar: bytes, tree: str, round_: str, seed: int, pace: str, hours: float, head: str,
             focus: str = "mix") -> dict:
        import shutil
        import threading
        work = Path("/work/tree")
        work.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(tree_tar), mode="r:gz") as tar:
            tar.extractall(work)
        name = f"{tree}-{pace}-s{seed}" + ("" if focus == "mix" else f"-{focus}")
        out, res = Path("/tmp/out") / name, Path("/vol") / round_ / name
        res.mkdir(parents=True, exist_ok=True)
        lock = threading.Lock()
        last = [0.0]

        def sync(force=False):
            if not force and time.time() - last[0] < 300:
                return
            last[0] = time.time()
            with lock:
                for p in out.rglob("*"):
                    rel = p.relative_to(out)
                    if p.is_file() and rel.parts[0] != "sessions" and not p.name.startswith("store.db"):
                        dst = res / rel
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(p, dst)
                vol.commit()

        sys.path.insert(0, str(work / "lab" / "soak"))
        os.chdir(work)
        os.environ["SOAK_TREE"] = f"{tree} {head}"
        ft = Path("/usr/lib/x86_64-linux-gnu/faketime/libfaketime.so.1").exists()
        args = (["--seed", str(seed), "--hours", str(hours), "--pace", pace, "--out", str(out), "--focus", focus]
                + (["--faketime"] if ft else []))
        # day.py runs as a child so its imports resolve inside the tree; it syncs through a flag file.
        p = subprocess.Popen([sys.executable, str(work / "lab" / "soak" / "day.py"), *args], cwd=work,
                             stdout=open("/tmp/day.out", "w"), stderr=subprocess.STDOUT)
        while p.poll() is None:
            time.sleep(20)
            if out.exists():
                sync()
        if out.exists():
            shutil.copyfile("/tmp/day.out", out / "logs" / "day.out") if (out / "logs").exists() else None
            # the store's file: size and an integrity check, never the file itself
            db = out / "store.db"
            if db.exists():
                r = subprocess.run(["sqlite3", str(db), "pragma integrity_check; select count(*) from events; "
                                    "select count(*) from seconds;"], capture_output=True, text=True)
                (out / "store_check.txt").write_text(r.stdout + r.stderr)
            sync(force=True)
        try:
            return json.loads((out / "summary.json").read_text())
        except (OSError, ValueError):
            return {"error": "no summary", "exit": p.returncode, "tail": Path("/tmp/day.out").read_text()[-3000:]}

    @app.function(image=image, cpu=1.0, memory=2048, timeout=7 * 3600, volumes={"/vol": vol})
    def day_real(*args):
        return _day(*args)

    @app.function(image=image, cpu=1.5, memory=2048, timeout=5 * 3600, volumes={"/vol": vol})
    def day_fast(*args):
        return _day(*args)

    @app.local_entrypoint()
    def main(round: str, plan: str, seed0: int = 1000):
        trees = {t["tree"]: t for t in json.loads((TREES / round / "trees.json").read_text())}
        calls, seed = [], seed0
        for item in plan.split(","):
            tree, pace, n, hours, *rest = item.split(":")
            focus = rest[0] if rest else "mix"
            tar = (TREES / round / f"{tree}.tar.gz").read_bytes()
            fn = day_real if pace == "real" else day_fast
            for _ in range(int(n)):
                seed += 1
                calls.append((tree, pace, seed, fn.spawn(tar, tree, round, seed, pace, float(hours), trees[tree]["head"], focus)))
        print(f"{len(calls)} days started: seeds {seed0 + 1}-{seed}", flush=True)
        for tree, pace, s, c in calls:
            try:
                r = c.get()
                print(json.dumps({"tree": tree, "pace": pace, "seed": s, "hours": r.get("hours_run"),
                                  "visits": r.get("visits"), "problems": r.get("problems"), "error": r.get("error")}), flush=True)
            except Exception as e:
                print(json.dumps({"tree": tree, "pace": pace, "seed": s, "error": repr(e)}), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("trees")
    t.add_argument("--round", required=True)
    t.add_argument("--prs", default="")
    t.add_argument("--heroes-ref", default="", help="build heroes from this branch instead of main (then --prs on top)")
    t.add_argument("--tree", action="append", default=[], help="name:prs:layout, instead of main and heroes")
    f = sub.add_parser("fetch")
    f.add_argument("--round", required=True)
    a = ap.parse_args()
    {"trees": cmd_trees, "fetch": cmd_fetch}[a.cmd](a)
