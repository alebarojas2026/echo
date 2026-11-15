"""Tests for radio.report_hci."""

import pytest
from radio.report_hci import GATE_PATH, MIN_RATES, check, main, parse_gate2_md, warnings

from radio.report_hci import BEACON_OF

# Built from radio/nodes.json (through MIN_RATES), so these tests hold for any layout: a passing
# row for every Bluetooth link, a Pi's beacon at 25/s and the others at 8/s.
GOOD = [(link, BEACON_OF[link], "25.0" if rate == 20.0 else "8.0", "PASS") for link, rate in MIN_RATES.items()]
LAST = GOOD[-1][0]


def table(*rows):
    head = "## Gate 2 — Bluetooth raw scan (#20)\n\n| Link | Beacon | Adverts/s | Result |\n|---|---|---|---|\n"
    return head + "".join("| " + " | ".join(r) + " |\n" for r in rows)


def with_row(link, rate, result="__", beacon=None):
    """GOOD with the row for `link` replaced."""
    return [r if r[0] != link else (link, beacon or r[1], rate, result) for r in GOOD]


def test_parse_passing_rows():
    rows = parse_gate2_md(table(*with_row("pi5>unoq:ble", "25.4", "PASS"), ("west>pi5:ble", "W", "7.0", "PASS")))
    assert set(rows) == set(MIN_RATES)
    assert rows["pi5>unoq:ble"][0]["rate"] == pytest.approx(25.4)
    assert rows["west>pi5:ble"][-1]["rate"] == pytest.approx(7.0)
    assert rows["pi5>unoq:ble"][0]["result"] == "PASS"
    assert check(rows) == []  # exactly 7.0 passes


@pytest.mark.parametrize("link, rate, why", [
    ("pi5>unoq:ble", "18.0", "rate 18.0 < 20.0"),
    ("east>unoq:ble", "5.1", "rate 5.1 < 7.0"),
    ("west>pi5:ble", "6.9", "rate 6.9 < 7.0"),
])
def test_a_low_rate_fails(link, rate, why):
    assert check(parse_gate2_md(table(*with_row(link, rate, "FAIL")))) == [f"{link}: {why} adverts/s"]


def test_unmeasured():
    rows = parse_gate2_md(table(*[(r[0], r[1], "__", "__") for r in GOOD]))
    assert check(rows) == [f"{link}: not yet measured" for link in MIN_RATES]


def test_missing_link():
    rows = parse_gate2_md(table(*GOOD[:-1]))
    assert check(rows) == [f"{LAST} not found in the Gate 2 table"]


def test_a_failing_run_among_three_fails_the_gate():
    rows = parse_gate2_md(table(*GOOD, ("east>unoq:ble", "E", "4.0", "FAIL"), ("east>unoq:ble", "E", "9.0", "PASS")))
    assert check(rows) == ["east>unoq:ble: rate 4.0 < 7.0 adverts/s"]


def test_the_rate_decides_not_the_result_column():
    rows = parse_gate2_md(table(*[(r[0], r[1], r[2], "__") for r in GOOD]))
    assert check(rows) == []
    assert warnings(rows) == []


def test_a_result_that_disagrees_with_the_rate_is_only_a_warning():
    rows = parse_gate2_md(table(*with_row("pi5>unoq:ble", "18.0", "PASS")))
    assert check(rows) == ["pi5>unoq:ble: rate 18.0 < 20.0 adverts/s"]
    assert warnings(rows) == ["pi5>unoq:ble: row with 18.0/s says PASS, the rate says FAIL"]


@pytest.mark.parametrize("cell", ["25.0/s", "~25", "25,0"])
def test_an_unreadable_rate_says_so(cell):
    rows = parse_gate2_md(table(*with_row("pi5>unoq:ble", cell, "PASS")))
    assert check(rows) == [f"pi5>unoq:ble: can't read rate '{cell}' (write a bare number)"]


def test_beacon_must_match_the_link():
    rows = parse_gate2_md(table(*with_row("east>pi5:ble", "8.0", beacon="W")))
    assert check(rows) == ["east>pi5:ble: beacon is 'W', should be 'E'"]


def test_rows_outside_the_gate_2_section_are_ignored():
    text = f"## Gate 1\n| {LAST} | {BEACON_OF[LAST]} | 99 | PASS |\n\n" + table(*GOOD[:-1])
    assert check(parse_gate2_md(text)) == [f"{LAST} not found in the Gate 2 table"]


def test_the_real_gate_md_has_one_unmeasured_row_per_bluetooth_link():
    rows = parse_gate2_md(GATE_PATH.read_text(encoding="utf-8"))
    assert {link: [(e["beacon"], e["rate_text"]) for e in rows[link]] for link in rows} == {
        link: [(BEACON_OF[link], "__")] for link in MIN_RATES}
    assert check(rows) == [f"{link}: not yet measured" for link in MIN_RATES]


def test_main_prints_the_lowest_rates(monkeypatch, tmp_path, capsys):
    gate = tmp_path / "GATE.md"
    gate.write_text(table(*GOOD, ("pi5>unoq:ble", "S", "21.5", "PASS")), encoding="utf-8")
    monkeypatch.setattr("radio.report_hci.GATE_PATH", gate)
    main()
    lowest = {link: "21.5" if link == "pi5>unoq:ble" else rate for link, _, rate, _ in GOOD}
    assert capsys.readouterr().out.strip() == (
        "GATE 2 PASS (lowest of each: " + ", ".join(f"{link}: {lowest[link]}/s" for link in MIN_RATES) + ")")


def test_main_fails_on_the_template(monkeypatch, capsys):
    with pytest.raises(SystemExit) as stopped:
        main()
    assert stopped.value.code == 1
    assert capsys.readouterr().out.startswith("GATE 2 FAIL")


def test_rates_and_letters_come_from_nodes_json():
    from radio.nodes import DOC, LINKS
    from radio.report_hci import BEACON_OF, MIN_RATES
    pis = {n["id"] for n in DOC["nodes"] if "receiver" in n["roles"] and "beacon" in n["roles"]}
    assert set(MIN_RATES) == {lid for lid, link in LINKS.items() if link["kind"] == "ble"}
    for link_id, rate in MIN_RATES.items():
        assert rate == (20.0 if LINKS[link_id]["tx"] in pis else 7.0)
    # Today's layout gives exactly the old hand-written table.
    assert {k: MIN_RATES[k] for k in ("pi5>unoq:ble", "east>unoq:ble", "west>pi5:ble")} == \
        {"pi5>unoq:ble": 20.0, "east>unoq:ble": 7.0, "west>pi5:ble": 7.0}
    assert BEACON_OF["pi5>unoq:ble"] == "S" and BEACON_OF["east>pi5:ble"] == "E" and BEACON_OF["west>unoq:ble"] == "W"
