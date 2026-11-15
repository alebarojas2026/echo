"""Section 10: the bodies of the board's web server (POST /ask, GET /history, GET /report).

They are not bus messages, so they are checked by name."""
import json
from pathlib import Path

import pytest

from contracts import check

FIXTURES = Path(__file__).parent.parent / "fixtures"

# What each line of the invalid fixtures gets wrong, in order.
BAD_QUESTIONS = [
    "$.question",                       # only spaces
    "'question' is a required property",
    "$.question",                       # not a string
]
BAD_REPLIES = [
    "$.tool",                           # no such tool
    "$.rows",                           # no tool, but rows
    "$.answer",                         # no tool, but the answer doesn't list what can be asked
    "'zone' is a required property",    # a tool always says what it was run with
    "$.args.zone",                      # zone 4: the desk layout has zones 1 and 2
    "$.args.link",                      # a hall link is never a core link
    "$.picked_by",
    "'rows' is a required property",
    "$.ms",                             # the board always times its answer
    "$.span.to_t",                      # a span runs forwards
    "'to_t' is a required property",
]
BAD_HISTORIES = [
    "$.rows[0].zone",                   # not known, but zone 0: unknown is never "nobody"
    "$.rows[0].zone",                   # nobody there, but zone 2
    "$.rows[0].alert",                  # alert is true or false here
    "$.rows[0].tamper[0]",              # no such node
    "$.step_s",                         # one row a second
    "more than 30 minutes",
    "not oldest first",
    "a row outside",
    "$.to_t",                           # the stretch runs forwards
    "'rows' is a required property",
]
BAD_LAYOUTS = [
    "$",                                # nothing to save
    "$.room.scale",                     # a scale of 10 is a typo
    "'cut_m' is a required property",
    "$.hall_beacons[0].node",           # only hall beacons are placed: the layout's own nodes stay in nodes.json
    "$.hall_beacons[0].xyz_m",          # x, y and z
    "$.hall_beacons[0].xyz_m[2]",       # 40 m up
    "'nodes' was unexpected",
]
BAD_NODES = [
    "$.armed.hold_s",                   # an intrusion that needs no time at all
    "$.armed.hold_s",                   # a number of seconds
    "'wait_s' was unexpected",
    "$.hall.links[0].id",               # only a hall link has an empty-hall level
    "'empty_quiet_db' is a required property",   # a link is listed only once it is calibrated
    "$.hall.links[0].empty_quiet_db",   # a quiet level is above 0
    "$.links[0].classifier",            # classifier is true or false
    "$.nodes[0].device",                # a short lower-case word, as in the screen's model names
]
BAD_PRIVACY = [
    "does not allow 0",                 # not running, yet it says 0 images: never a zero in place of an unknown
    "'bytes_out' is a required property",
    "$.bytes_out",                      # an unknown is ok false, not null
    "'why' is a required property",
    "$.bytes_out",
]
BAD_CLOCKS = [
    "$.t",                              # epoch ms, a whole number
    "'busy' is a required property",    # null when nothing stands in the way
    "'why' is a required property",     # a failed step says why
]
BAD_CLOCK_SETS = [
    "'stepping' is a required property",
    "'why' is a required property",     # a refusal says why
    "does not allow True",              # refused, so nothing is stepped
]
BAD_REPORTS = [
    "$.intrusions[0]",                  # a hall link is its link id, not the beacon's letter
    "$.intrusions[0].zone",             # never in zone 0
    "$.intrusions[0]",                  # a zone or a hall link
    "$.tamper[0].node",                 # no such node
    "$.armed_to_t",                     # disarmed before it was armed
    "$.text",                           # the report always has words
    "'passed_by' is a required property",   # null until the brain has such a rule, never left out
]


def lines(name):
    return (FIXTURES / name).read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize("schema", ["ask_question", "ask_reply", "history", "report", "layout", "nodes", "privacy", "clock", "clock_set"])
def test_valid_ask_bodies_pass(schema):
    count, failures, warnings = check.check_lines(lines(f"{schema}_valid.jsonl"), schema)
    assert count >= 1 and failures == [] and warnings == []


@pytest.mark.parametrize("schema, reasons", [("ask_question", BAD_QUESTIONS), ("ask_reply", BAD_REPLIES),
                                             ("history", BAD_HISTORIES), ("report", BAD_REPORTS),
                                             ("layout", BAD_LAYOUTS), ("nodes", BAD_NODES),
                                             ("privacy", BAD_PRIVACY),
                                             ("clock", BAD_CLOCKS), ("clock_set", BAD_CLOCK_SETS)])
def test_each_invalid_ask_body_fails_for_its_reason(schema, reasons):
    bad = lines(f"{schema}_invalid.jsonl")
    assert len(bad) == len(reasons)
    for no, (line, reason) in enumerate(zip(bad, reasons), 1):
        failures = check.check_lines([line], schema)[1]
        assert any(reason in err for _, err in failures), f"line {no}: {failures}"


def test_ask_bodies_are_not_bus_messages():
    assert not {"ask_question", "ask_reply", "history", "report", "layout", "nodes"} & set(check.TYPES)
    assert "unknown type" in check.check_lines(lines("ask_reply_valid.jsonl"))[1][0][1]


def test_the_command_line_checks_ask_bodies_by_name(capsys):
    assert check.main(["--as", "ask_reply", str(FIXTURES / "ask_reply_valid.jsonl")]) == 0
    assert check.main(["--as", "ask_reply", str(FIXTURES / "ask_reply_invalid.jsonl")]) == 1
    assert check.main(["--as", "ask_question", str(FIXTURES / "ask_question_valid.jsonl")]) == 0
    assert check.main(["--as", "history", str(FIXTURES / "history_valid.jsonl")]) == 0
    assert check.main(["--as", "report", str(FIXTURES / "report_invalid.jsonl")]) == 1
    assert "ask_reply_invalid.jsonl:1:" in capsys.readouterr().out


def test_a_span_is_optional_on_an_answer():
    replies = [json.loads(line) for line in lines("ask_reply_valid.jsonl")]
    assert [("span" in r) for r in replies] == [False, False, False, True]


def test_a_report_counts_the_people_who_passed_by():
    reports = [json.loads(line) for line in lines("report_valid.jsonl")]
    assert [r["passed_by"] for r in reports] == [3, 0, None]            # null: a server that does not count them yet


def test_the_repo_nodes_json_passes_and_its_optional_parts_may_be_missing():
    doc = json.loads((FIXTURES.parent.parent / "radio" / "nodes.json").read_text(encoding="utf-8"))
    assert check.errors(doc, "nodes") == []
    assert check.errors({**doc, "armed": {"hold_s": 3}}, "nodes") == []
    calibrated = {**doc["hall"], "links": [{"id": "h>unoq:ble", "empty_quiet_db": 0.8}]}
    assert check.errors({**doc, "hall": calibrated}, "nodes") == []
    assert "$.armed.hold_s" in check.errors({**doc, "armed": {"hold_s": -1}}, "nodes")[0]


def test_history_keeps_not_known_apart_from_nobody():
    rows = [row for line in lines("history_valid.jsonl") for row in json.loads(line)["rows"]]
    assert {row["present"] for row in rows} == {True, False, None}
    assert all(row["zone"] is None for row in rows if row["present"] is None)
