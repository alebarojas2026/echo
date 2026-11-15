from ci.report import (
    LaneResult,
    conflict_rows,
    lane_result,
    mark_known,
    parse_pytest,
    parse_tsc,
    parse_vitest,
    render_pairs,
    render_summary,
    render_table,
)
from ci.trees import Tree

PYTEST_FAIL = """\
..F.s
=========================== short test summary info ============================
FAILED brain/tests/test_core.py::test_tmp_path - FileNotFoundError: C:\\Temp
ERROR brain/tests/test_main.py::test_boot - ImportError: no module
1 failed, 3 passed, 1 skipped, 1 error in 2.31s
"""

VITEST_FAIL = """\
 FAIL  tests/hud.test.ts > arrival > shows Found you
 Test Files  1 failed | 9 passed (10)
      Tests  1 failed | 52 passed (53)
"""


def step(name, code, output="", kind=None):
    s = {"name": name, "exit": code, "seconds": 1.0, "output": output}
    if kind:
        s["kind"] = kind
    return s


def test_parse_pytest_counts_and_failures():
    counts, failures = parse_pytest(PYTEST_FAIL)
    assert counts == {"failed": 1, "passed": 3, "skipped": 1, "errors": 1}
    assert failures[0].startswith("brain/tests/test_core.py::test_tmp_path - ")
    assert failures[1].startswith("brain/tests/test_main.py::test_boot")


def test_parse_pytest_reads_the_banner_form_too():
    counts, _ = parse_pytest("====== 12 passed, 2 warnings in 0.50s ======\n")
    assert counts == {"passed": 12}


def test_parse_vitest():
    counts, failures = parse_vitest(VITEST_FAIL)
    assert counts == {"failed": 1, "passed": 52}
    assert failures == ["tests/hud.test.ts > arrival > shows Found you"]


def test_parse_tsc_both_formats():
    out = "src/a.ts(3,7): error TS2322: Type 'x' is not assignable.\nsrc/b.ts:9:1 - error TS2304: Cannot find name 'y'.\n"
    assert parse_tsc(out) == ["src/a.ts:3:7 TS2322 Type 'x' is not assignable.", "src/b.ts:9:1 TS2304 Cannot find name 'y'."]


def test_lane_result_pass():
    raw = {"steps": [step("deps", 0), step("pytest", 0, "40 passed in 1.0s\n")], "seconds": 7.5}
    r = lane_result("main", "sim", raw)
    assert (r.status, r.counts, r.seconds) == ("pass", "40 passed", 7.5)


def test_lane_result_fail_lists_failing_tests():
    raw = {"steps": [step("pytest", 1, PYTEST_FAIL)], "seconds": 3}
    r = lane_result("#491", "brain", raw)
    assert r.status == "fail"
    assert r.counts == "3 passed, 1 failed, 1 errors, 1 skipped"
    assert len(r.failures) == 2


def test_lane_result_setup_failure_and_timeout():
    r = lane_result("main", "x", {"steps": [step("deps", 1, "ERROR: No matching distribution for llama\n")], "seconds": 4})
    assert r.status == "fail" and r.failures[0].startswith("deps failed: ERROR: No matching")
    r = lane_result("main", "x", {"steps": [step("pytest", None, "....\n[timed out after 560 s]")], "seconds": 600})
    assert r.status == "timeout"


def test_lane_result_no_tests_and_exception():
    r = lane_result("main", "x", {"steps": [step("pytest", 5, "no tests ran in 0.01s\n")], "seconds": 1})
    assert r.status == "no tests" and r.ok
    r = lane_result("main", "x", RuntimeError("container died"))
    assert r.status == "error" and not r.ok


def test_web_lane_result():
    raw = {
        "steps": [
            step("npm ci", 0),
            step("tsc", 2, "src/a.ts(3,7): error TS2322: bad\n", "tsc"),
            step("vitest", 1, VITEST_FAIL, "vitest"),
            step("vite build", 0, "built in 3s", "build"),
        ],
        "seconds": 50,
    }
    r = lane_result("main", "web", raw)
    assert r.status == "fail"
    assert r.counts == "tsc 1 errors, 52 passed, 1 failed, vite build ok"
    assert r.failures == ["tsc: src/a.ts:3:7 TS2322 bad", "vitest: tests/hud.test.ts > arrival > shows Found you"]


def test_mark_known_flags_failures_already_on_main():
    rows = [
        LaneResult("main", "brain", "fail", failures=["t.py::a - boom"]),
        LaneResult("#1", "brain", "fail", failures=["t.py::a - boom"]),
        LaneResult("#2", "brain", "fail", failures=["t.py::a - boom", "t.py::b - new"]),
    ]
    mark_known(rows)
    assert [r.note for r in rows] == ["", "same as main", ""]


def test_table_has_one_row_per_lane_and_escapes_pipes():
    rows = [
        LaneResult("main", "sim", "pass", "40 passed", 7.2),
        LaneResult("#5", "web", "fail", "tsc ok", 41, ["vitest: a | b"] + [f"x{i}" for i in range(4)]),
    ]
    table = render_table(rows).splitlines()
    assert table[0] == "| Tree | Lane | Result | Counts | Seconds | First failures |"
    assert table[2] == "| main | sim | pass | 40 passed | 7 |  |"
    assert "**FAIL**" in table[3] and "a \\| b" in table[3] and "+2 more" in table[3]


def test_conflicts_are_reported_with_their_files_and_not_run():
    trees = [Tree("#7", None, [7], ["brain/core.py", "radio/nodes.json"]), Tree("#8", "abc", [8])]
    rows = conflict_rows(trees) + [LaneResult("#8", "sim", "pass", "1 passed", 1)]
    assert rows[0].status == "conflict" and rows[0].failures == ["brain/core.py", "radio/nodes.json"]
    summary = render_summary(trees, rows)
    assert "- #7: **conflict** with main in `brain/core.py`, `radio/nodes.json`; not run" in summary
    assert "- #8: all 1 lanes pass" in summary


def test_stack_summary_names_the_prs_left_out():
    t = Tree("stack", "abc", [1, 3], skipped=[(2, ["web/src/main.ts"])])
    summary = render_summary([t], [LaneResult("stack", "web", "pass")])
    assert summary.splitlines() == [
        "- stack #1 + #3: all 1 lanes pass",
        "  - #2 left out of the stack: conflicts in `web/src/main.ts`",
    ]


def test_render_pairs():
    assert render_pairs([]) == "No two of these PRs conflict with each other."
    assert render_pairs([(1, 2, ["a.py"])]).splitlines()[-1] == "| #1 | #2 | a.py |"
