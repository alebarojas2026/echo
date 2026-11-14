"""Tests for radio.report_hci."""

import pytest
from radio.report_hci import GATE_PATH, check, main, parse_gate2_md, warnings

PASSING_MD = """
## Gate 2 — Bluetooth raw scan (#20)

**Pass criteria:** Pi beacon ≥ 20 adverts/s; each phone beacon ≥ 7 adverts/s.

| Beacon | Node ID | Adverts/s | Result |
|--------|---------|-----------|--------|
| pi5    | S       | 25.4      | PASS   |
| east   | E       | 8.2       | PASS   |
| west   | W       | 7.5       | PASS   |

**Overall Gate 2:** PASS
"""

FAILING_PI_RATE_MD = """
## Gate 2 — Bluetooth raw scan (#20)

| Beacon | Node ID | Adverts/s | Result |
|--------|---------|-----------|--------|
| pi5    | S       | 18.0      | FAIL   |
| east   | E       | 8.0       | PASS   |
| west   | W       | 8.0       | PASS   |
"""

FAILING_PHONE_RATE_MD = """
## Gate 2 — Bluetooth raw scan (#20)

| Beacon | Node ID | Adverts/s | Result |
|--------|---------|-----------|--------|
| pi5    | S       | 22.0      | PASS   |
| east   | E       | 5.1       | FAIL   |
| west   | W       | 7.0       | PASS   |
"""

UNMEASURED_MD = """
## Gate 2 — Bluetooth raw scan (#20)

| Beacon | Node ID | Adverts/s | Result |
|--------|---------|-----------|--------|
| pi5    | S       | __        | __     |
| east   | E       | __        | __     |
| west   | W       | __        | __     |
"""

MISSING_BEACON_MD = """
## Gate 2 — Bluetooth raw scan (#20)

| Beacon | Node ID | Adverts/s | Result |
|--------|---------|-----------|--------|
| pi5    | S       | 25.0      | PASS   |
| east   | E       | 8.0       | PASS   |
"""


def test_parse_passing_rows():
    rows = parse_gate2_md(PASSING_MD)
    assert len(rows) == 3
    assert rows["pi5"][0]["rate"] == pytest.approx(25.4)
    assert rows["east"][0]["rate"] == pytest.approx(8.2)
    assert rows["west"][0]["rate"] == pytest.approx(7.5)
    assert rows["pi5"][0]["result"] == "PASS"


def test_passing_gate():
    rows = parse_gate2_md(PASSING_MD)
    assert check(rows) == []


def test_failing_pi_rate():
    rows = parse_gate2_md(FAILING_PI_RATE_MD)
    failures = check(rows)
    assert any("pi5" in f and "18.0 < 20.0" in f for f in failures)


def test_failing_phone_rate():
    rows = parse_gate2_md(FAILING_PHONE_RATE_MD)
    failures = check(rows)
    assert any("east" in f and "5.1 < 7.0" in f for f in failures)


def test_unmeasured():
    rows = parse_gate2_md(UNMEASURED_MD)
    failures = check(rows)
    assert len(failures) == 3
    assert all("not yet measured" in f for f in failures)


def test_missing_beacon():
    rows = parse_gate2_md(MISSING_BEACON_MD)
    failures = check(rows)
    assert any("west" in f and "not found" in f for f in failures)


def table(*rows):
    head = "## Gate 2 — Bluetooth raw scan (#20)\n\n| Beacon | Node ID | Adverts/s | Result |\n|---|---|---|---|\n"
    return head + "".join("| " + " | ".join(r) + " |\n" for r in rows)


GOOD = [("pi5", "S", "25.0", "PASS"), ("east", "E", "8.0", "PASS"), ("west", "W", "8.0", "PASS")]


def test_a_failing_run_among_three_fails_the_gate():
    rows = parse_gate2_md(table(*GOOD, ("east", "E", "4.0", "FAIL"), ("east", "E", "9.0", "PASS")))
    assert check(rows) == ["beacon 'east': rate 4.0 < 7.0 adverts/s"]


def test_the_rate_decides_not_the_result_column():
    rows = parse_gate2_md(table(("pi5", "S", "25.0", "__"), ("east", "E", "8.0", "__"), ("west", "W", "7.0", "__")))
    assert check(rows) == []  # exactly 7.0 passes
    assert warnings(rows) == []


def test_a_result_that_disagrees_with_the_rate_is_only_a_warning():
    rows = parse_gate2_md(table(("pi5", "S", "18.0", "PASS"), *GOOD[1:]))
    assert check(rows) == ["beacon 'pi5': rate 18.0 < 20.0 adverts/s"]
    assert warnings(rows) == ["beacon 'pi5': row with 18.0/s says PASS, the rate says FAIL"]


@pytest.mark.parametrize("cell", ["25.0/s", "~25", "25,0"])
def test_an_unreadable_rate_says_so(cell):
    rows = parse_gate2_md(table(("pi5", "S", cell, "PASS"), *GOOD[1:]))
    assert check(rows) == [f"beacon 'pi5': can't read rate '{cell}' (write a bare number)"]


def test_node_id_must_match_the_beacon():
    rows = parse_gate2_md(table(GOOD[0], ("east", "W", "8.0", "PASS"), ("west", "E", "8.0", "PASS")))
    assert check(rows) == ["beacon 'east': node ID is 'W', should be 'E'",
                           "beacon 'west': node ID is 'E', should be 'W'"]


def test_rows_outside_the_gate_2_section_are_ignored():
    text = "## Gate 1\n| east | E | 99 | PASS |\n\n" + table(*GOOD[:2])
    assert check(parse_gate2_md(text)) == ["beacon 'west' not found in Gate 2 table"]


def test_the_real_gate_md_parses_as_three_unmeasured_rows():
    rows = parse_gate2_md(GATE_PATH.read_text(encoding="utf-8"))
    assert {b: [(e["node_id"], e["rate_text"]) for e in rows[b]] for b in rows} == {
        "pi5": [("S", "__")], "east": [("E", "__")], "west": [("W", "__")]}
    assert check(rows) == [f"beacon '{b}': not yet measured" for b in ("pi5", "east", "west")]


def test_main_prints_the_lowest_rates(monkeypatch, tmp_path, capsys):
    gate = tmp_path / "GATE.md"
    gate.write_text(table(*GOOD, ("pi5", "S", "21.5", "PASS")), encoding="utf-8")
    monkeypatch.setattr("radio.report_hci.GATE_PATH", gate)
    main()
    assert capsys.readouterr().out.strip() == "GATE 2 PASS (lowest of each: pi5: 21.5/s, east: 8.0/s, west: 8.0/s)"
