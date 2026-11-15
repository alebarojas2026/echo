"""Run every lane's tests on Debian 13 and Python 3.13 (the board's), from this PC, on Modal.

    python ci/modal_ci.py --prs 415,451,468 [--each | --together] [--main]

Each PR is merged into origin/main here (a conflict is reported and not run); --together stacks
the PRs in the given order. Each tree's tracked files go up as a tarball, one container runs
each (tree, lane), and a Markdown table goes to stdout and to ci-out/. Nothing is posted to
GitHub, and nothing in the demo uses this.
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ci import lanes as lanes_mod  # noqa: E402
from ci import report, trees  # noqa: E402

# Modal list prices: 2 CPU cores and 4 GiB per container.
DOLLARS_PER_CONTAINER_SECOND = 2 * 0.0000131 + 4 * 0.00000222
EXPECTED_SECONDS_PER_LANE = 90


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--prs", default="", help="comma-separated PR numbers, e.g. 415,451,468")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--each", action="store_true", help="each PR merged into main alone (the default)")
    mode.add_argument("--together", action="store_true", help="all PRs stacked on main in the given order")
    p.add_argument("--main", action="store_true", help="also test origin/main alone")
    p.add_argument("--lanes", default="", help="only these lanes, comma-separated")
    p.add_argument("--repeat", type=int, default=1, help="run every lane N times (to check a flaky test)")
    p.add_argument("--max-dollars", type=float, default=2.0, help="refuse to start if the estimate is higher")
    p.add_argument("--dry-run", action="store_true", help="build the trees and print the plan; no Modal")
    p.add_argument("--no-fetch", action="store_true", help="use the refs already fetched")
    p.add_argument("--repo", default=str(REPO), help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    args.pr_list = [int(x) for x in args.prs.replace(" ", "").split(",") if x]
    if not args.pr_list and not args.main:
        p.error("give --prs, --main, or both")
    if not args.together:
        args.each = True
    return args


def plan_trees(repo, main, args):
    out = [trees.main_tree(repo, main)] if args.main else []
    if args.pr_list and args.together:
        out.append(trees.stack_tree(repo, main, args.pr_list))
    elif args.pr_list:
        out += trees.each_trees(repo, main, args.pr_list)
    return out


def plan_jobs(repo, tree_list, only=()):
    """(tree name, lane, steps) for every runnable tree, and each tree's tarball."""
    jobs, blobs = [], {}
    for t in tree_list:
        if not t.runnable:
            continue
        files = trees.paths(repo, t.commit)
        pkg = trees.show(repo, t.commit, "web/package.json") if "web/package.json" in files else None
        file_set = set(files)
        for lane in lanes_mod.discover_lanes(file_set, pkg):
            if only and lane not in only:
                continue
            jobs.append((t.name, lane, lanes_mod.lane_steps(lane, file_set, pkg)))
        blobs[t.name] = trees.tarball(repo, t.commit)
    return jobs, blobs


def not_open(prs):
    """The PRs GitHub no longer lists as open (read-only `gh` call; skipped if gh is missing)."""
    if not prs:
        return []
    try:
        proc = subprocess.run(
            ["gh", "pr", "list", "--state", "open", "--limit", "500", "--json", "number"],
            cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    open_now = {row["number"] for row in json.loads(proc.stdout or b"[]")}
    return [n for n in prs if n not in open_now]


def write_image_inputs(repo, main):
    """Requirement lines and the web lockfile from origin/main, for the cached image layers."""
    d = repo / "ci-out" / ".image"
    (d / "web").mkdir(parents=True, exist_ok=True)
    files = trees.paths(repo, main)
    reqs = {p: trees.show(repo, main, p) or "" for p in files if Path(p).name.startswith("requirements") and p.endswith(".txt")}
    (d / "requirements.txt").write_text("\n".join(lanes_mod.requirement_lines(reqs)) + "\n", encoding="utf-8")
    for name in ("package.json", "package-lock.json"):
        text = trees.show(repo, main, f"web/{name}")
        if text is not None:
            (d / "web" / name).write_text(text, encoding="utf-8", newline="\n")


def output_name(repo, tree_list, main, args):
    runnable = [t for t in tree_list if t.runnable]
    if len(tree_list) == 1 and runnable:
        return trees.out(repo, "rev-parse", "--short", runnable[0].commit)
    mode = "together" if args.together else "each"
    tags = (["main"] if args.main else []) + ([mode] if args.pr_list else [])
    return trees.out(repo, "rev-parse", "--short", main) + "-" + "-".join(tags)


def write_logs(log_dir, raws):
    log_dir.mkdir(parents=True, exist_ok=True)
    for (tree, lane), raw in raws.items():
        safe = "".join(c if c.isalnum() else "_" for c in tree.replace("#", "pr")).strip("_")
        if isinstance(raw, BaseException):
            body = f"{type(raw).__name__}: {raw}\n"
        else:
            body = f"versions: {' '.join(raw.get('versions', []))}\n"
            for s in raw["steps"]:
                body += f"\n===== {s['name']} (exit {s['exit']}, {s['seconds']} s)\n{s['output']}\n"
        (log_dir / f"{safe}__{lane}.log").write_text(body, encoding="utf-8")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args(argv)
    repo = Path(args.repo)
    gone = not_open(args.pr_list)
    if gone:
        # A PR squash-merged since it was listed would show as a conflict with its own copy on main.
        print(f"skipping PRs that are no longer open: {', '.join(f'#{n}' for n in gone)}", file=sys.stderr)
        args.pr_list = [n for n in args.pr_list if n not in gone]
    if not args.no_fetch:
        trees.fetch(repo, args.pr_list)
    main_sha = trees.out(repo, "rev-parse", "refs/remotes/origin/main")
    tree_list = plan_trees(repo, main_sha, args)
    only = {x for x in args.lanes.split(",") if x}
    jobs, blobs = plan_jobs(repo, tree_list, only)
    labels = [name for name, _, _ in jobs]
    if args.repeat > 1:  # the same lane in several fresh containers, to tell a flaky test from a broken one
        jobs = [j for j in jobs for _ in range(args.repeat)]
        labels = [f"{name} (run {i % args.repeat + 1})" for i, (name, _, _) in enumerate(jobs)]
    estimate = len(jobs) * EXPECTED_SECONDS_PER_LANE * DOLLARS_PER_CONTAINER_SECOND
    print(f"main {main_sha[:7]}; {len([t for t in tree_list if t.runnable])} trees, {len(jobs)} containers, about ${estimate:.2f}", file=sys.stderr)
    for t in tree_list:
        if not t.runnable:
            print(f"  {t.name}: conflict in {', '.join(t.conflicts)}", file=sys.stderr)
        for pr, files in t.skipped:
            print(f"  stack: #{pr} left out, conflicts in {', '.join(files)}", file=sys.stderr)
    if args.dry_run:
        for name, lane, steps in jobs:
            print(f"  {name} {lane}: " + " && ".join(s["cmd"] for s in steps), file=sys.stderr)
        return 0
    if estimate > args.max_dollars:
        print(f"estimate ${estimate:.2f} is over --max-dollars {args.max_dollars}; not starting", file=sys.stderr)
        return 2

    raws = {}
    if jobs:
        write_image_inputs(repo, main_sha)
        from ci import remote  # imports modal; only needed for a real run

        started = time.monotonic()

        def progress(res):
            if isinstance(res, dict):
                print(f"  done {res['key']} {res['lane']} in {res['seconds']:.0f} s", file=sys.stderr)

        results = remote.run_all(jobs, blobs, progress)
        for label, (_, lane, _), res in zip(labels, jobs, results):
            raws[(label, lane)] = res
        wall = time.monotonic() - started
    else:
        wall = 0.0

    rows = report.conflict_rows(tree_list)
    rows += [report.lane_result(label, lane, raws[(label, lane)]) for label, (_, lane, _) in zip(labels, jobs)]
    report.mark_known(rows)
    spent = sum(r.seconds for r in rows) * DOLLARS_PER_CONTAINER_SECOND

    stamp = datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    versions = next((" ".join(r["versions"]) for r in raws.values() if isinstance(r, dict) and r.get("versions")), "")
    parts = [
        f"## CI run {stamp}",
        f"origin/main `{main_sha[:7]}`; Debian 13 (trixie) {versions}; {len(jobs)} containers, {wall:.0f} s wall, test time about ${spent:.2f} (Modal also bills container start-up; `modal billing report --for today` has the real figure).",
        "",
        report.render_summary(tree_list, rows),
        f"- skipped, no longer open: {', '.join(f'#{n}' for n in gone)}" if gone else "",
        "",
        report.render_table(rows),
    ]
    if args.together and len(args.pr_list) > 1:
        parts += ["", "### PR pairs that conflict with each other", "", report.render_pairs(trees.pair_conflicts(repo, main_sha, args.pr_list))]
    md = "\n".join(parts) + "\n"
    print(md)
    name = output_name(repo, tree_list, main_sha, args)
    out_dir = repo / "ci-out"
    out_dir.mkdir(exist_ok=True)
    (out_dir / f"{name}.md").write_text(md, encoding="utf-8")
    write_logs(out_dir / name, raws)
    (out_dir / f"{name}.json").write_text(json.dumps([r.__dict__ for r in rows], indent=1), encoding="utf-8")
    print(f"wrote ci-out/{name}.md and logs in ci-out/{name}/", file=sys.stderr)
    return 0 if all(r.ok for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
