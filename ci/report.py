"""Turn each lane's step outputs into one result row, and the rows into Markdown."""

import re
from dataclasses import dataclass, field

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
PYTEST_COUNT = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected)\b")
PYTEST_SUMMARY = re.compile(r"^=*\s*((?:\d+ \w+(?:, )?)+).* in [\d.]+s")
VITEST_TESTS = re.compile(r"^\s*Tests\s+(.+?)\s*\((\d+)\)\s*$")
VITEST_FAIL = re.compile(r"^\s*(?:FAIL|×|✗)\s+(\S.*?)\s*(?:\[[^\]]*\])?\s*$")
TSC_ERROR = re.compile(r"^(\S.*?)(?:\((\d+),(\d+)\)|:(\d+):(\d+))\s*[:-]\s*error (TS\d+): (.*)$")
MAX_FAILURES = 3
CELL_MAX = 140


def clean(text):
    return ANSI.sub("", text or "").replace("\r\n", "\n")


def parse_pytest(output):
    """Counts from pytest's last summary line, and the FAILED/ERROR lines of its short summary."""
    text = clean(output)
    counts = {}
    for line in text.splitlines():
        m = PYTEST_SUMMARY.match(line.strip())
        if m:
            counts = {}
            for n, word in PYTEST_COUNT.findall(m.group(1)):
                key = "errors" if word.startswith("error") else word
                counts[key] = counts.get(key, 0) + int(n)
    failures = []
    for line in text.splitlines():
        if line.startswith(("FAILED ", "ERROR ")):
            item = line.split(" ", 1)[1].strip()
            if item not in failures:
                failures.append(item)
    return counts, failures


def parse_vitest(output):
    text = clean(output)
    counts = {}
    for line in text.splitlines():
        m = VITEST_TESTS.match(line)
        if m:
            counts = {}
            for part in m.group(1).split("|"):
                bits = part.strip().split(" ", 1)
                if len(bits) == 2 and bits[0].isdigit():
                    counts[bits[1].strip()] = int(bits[0])
    failures = []
    for line in text.splitlines():
        m = VITEST_FAIL.match(line)
        if m and m.group(1) not in failures:
            failures.append(m.group(1))
    return counts, failures


def parse_tsc(output):
    failures = []
    for line in clean(output).splitlines():
        m = TSC_ERROR.match(line.strip())
        if m:
            row, col = m.group(2) or m.group(4), m.group(3) or m.group(5)
            failures.append(f"{m.group(1)}:{row}:{col} {m.group(6)} {m.group(7)}")
    return failures


def last_lines(output, n=1):
    lines = [x.strip() for x in clean(output).splitlines() if x.strip()]
    errors = [x for x in lines if re.search(r"error|Error|ERR!", x)]
    return (errors or lines)[-n:]


@dataclass
class LaneResult:
    tree: str
    lane: str
    status: str  # pass, fail, timeout, error, no tests, conflict
    counts: str = ""
    seconds: float = 0.0
    failures: list = field(default_factory=list)
    note: str = ""

    @property
    def ok(self):
        return self.status in ("pass", "no tests")

    def failure_names(self):
        return {f.split(" - ", 1)[0] for f in self.failures}


def _fmt_counts(counts, order=("passed", "failed", "errors", "skipped", "xfailed", "xpassed")):
    keys = [k for k in order if counts.get(k)] + [k for k in counts if k not in order and counts[k]]
    return ", ".join(f"{counts[k]} {k}" for k in keys)


def lane_result(tree, lane, raw):
    """One row from the dict run_lane returns (or the exception it raised)."""
    if isinstance(raw, BaseException):
        return LaneResult(tree, lane, "error", note=f"{type(raw).__name__}: {raw}"[:CELL_MAX], failures=[f"{type(raw).__name__}: {raw}"])
    steps = raw["steps"]
    status, counts, failures, no_tests = "pass", [], [], False
    for step in steps:
        name, code, output = step["name"], step["exit"], step["output"]
        kind = step.get("kind") or ""
        if code is None:
            status = "timeout"
            failures.append(f"{name}: {output.strip().splitlines()[-1] if output.strip() else 'timed out'}")
            continue
        if name in ("deps", "npm ci"):
            if code != 0:
                status = "fail"
                failures.append(f"{name} failed: " + " ".join(last_lines(output)))
            continue
        if name == "pytest" or kind == "pytest":
            c, f = parse_pytest(output)
            if code == 5:  # pytest collected nothing
                counts.append("no tests")
                no_tests = True
                continue
            counts.append(_fmt_counts(c))
            if code != 0:
                status = "fail" if status != "timeout" else status
                failures.extend(f or last_lines(output))
        elif kind == "vitest" or name == "vitest":
            c, f = parse_vitest(output)
            counts.append(_fmt_counts(c))
            if code != 0:
                status = "fail" if status != "timeout" else status
                failures.extend(f"vitest: {x}" for x in (f or last_lines(output)))
        elif kind == "tsc" or name == "tsc":
            f = parse_tsc(output)
            counts.append("tsc ok" if code == 0 else f"tsc {len(f) or '?'} errors")
            if code != 0:
                status = "fail" if status != "timeout" else status
                failures.extend(f"tsc: {x}" for x in (f or last_lines(output)))
        else:
            counts.append(f"{name} ok" if code == 0 else f"{name} failed")
            if code != 0:
                status = "fail" if status != "timeout" else status
                failures.extend(f"{name}: {x}" for x in last_lines(output))
    if status == "pass" and no_tests and counts == ["no tests"]:
        status = "no tests"
    return LaneResult(tree, lane, status, ", ".join(c for c in counts if c), raw.get("seconds", 0.0), failures)


def mark_known(results, base="main"):
    """Label a failing lane whose failures all fail on `base` too, so new breakage stands out."""
    base_rows = {r.lane: r for r in results if r.tree == base}
    for r in results:
        b = base_rows.get(r.lane)
        if r.tree != base and r.status == "fail" and b and b.status == "fail" and r.failure_names() <= b.failure_names():
            r.note = f"same as {base}"


def _cell(text):
    text = str(text).replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= CELL_MAX else text[: CELL_MAX - 3] + "..."


def render_table(results):
    lines = ["| Tree | Lane | Result | Counts | Seconds | First failures |", "|---|---|---|---|---:|---|"]
    for r in results:
        status = r.status if r.ok else f"**{r.status.upper()}**"
        if r.note:
            status += f" ({r.note})"
        fails = "<br>".join(_cell(f) for f in r.failures[:MAX_FAILURES])
        if len(r.failures) > MAX_FAILURES:
            fails += f"<br>+{len(r.failures) - MAX_FAILURES} more"
        lines.append(f"| {r.tree} | {r.lane} | {status} | {_cell(r.counts)} | {r.seconds:.0f} | {fails} |")
    return "\n".join(lines)


def render_summary(trees, results):
    """One line per tree: all lanes pass, the failing lanes, or the conflict."""
    lines = []
    for t in trees:
        label = tree_label(t)
        if not t.runnable:
            lines.append(f"- {label}: **conflict** with main in {', '.join(f'`{f}`' for f in t.conflicts)}; not run")
            continue
        rows = [r for r in results if r.tree == t.name]
        bad = [r for r in rows if not r.ok]
        if not bad:
            lines.append(f"- {label}: all {len(rows)} lanes pass")
        else:
            parts = [f"{r.lane} ({r.status}{', ' + r.note if r.note else ''})" for r in bad]
            lines.append(f"- {label}: {len(rows) - len(bad)}/{len(rows)} lanes pass; failing: {', '.join(parts)}")
        for pr, files in t.skipped:
            lines.append(f"  - #{pr} left out of the stack: conflicts in {', '.join(f'`{f}`' for f in files)}")
    return "\n".join(lines)


def tree_label(t):
    if t.name == "stack":
        return "stack " + (" + ".join(f"#{p}" for p in t.prs) if t.prs else "(empty)")
    return t.name


def render_pairs(pairs):
    if not pairs:
        return "No two of these PRs conflict with each other."
    lines = ["| PR | PR | Files both change |", "|---|---|---|"]
    for a, b, files in pairs:
        lines.append(f"| #{a} | #{b} | {_cell(', '.join(files))} |")
    return "\n".join(lines)


def conflict_rows(trees):
    return [LaneResult(t.name, "-", "conflict", failures=list(t.conflicts)) for t in trees if not t.runnable]
