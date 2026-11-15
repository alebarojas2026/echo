"""Section 10: the two bodies of POST /ask. They are not bus messages, so they are checked by name."""
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
]


def lines(name):
    return (FIXTURES / name).read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize("schema", ["ask_question", "ask_reply"])
def test_valid_ask_bodies_pass(schema):
    count, failures, warnings = check.check_lines(lines(f"{schema}_valid.jsonl"), schema)
    assert count >= 1 and failures == [] and warnings == []


@pytest.mark.parametrize("schema, reasons", [("ask_question", BAD_QUESTIONS), ("ask_reply", BAD_REPLIES)])
def test_each_invalid_ask_body_fails_for_its_reason(schema, reasons):
    bad = lines(f"{schema}_invalid.jsonl")
    assert len(bad) == len(reasons)
    for no, (line, reason) in enumerate(zip(bad, reasons), 1):
        failures = check.check_lines([line], schema)[1]
        assert any(reason in err for _, err in failures), f"line {no}: {failures}"


def test_ask_bodies_are_not_bus_messages():
    assert not {"ask_question", "ask_reply"} & set(check.TYPES)
    assert "unknown type" in check.check_lines(lines("ask_reply_valid.jsonl"))[1][0][1]


def test_the_command_line_checks_ask_bodies_by_name(capsys):
    assert check.main(["--as", "ask_reply", str(FIXTURES / "ask_reply_valid.jsonl")]) == 0
    assert check.main(["--as", "ask_reply", str(FIXTURES / "ask_reply_invalid.jsonl")]) == 1
    assert check.main(["--as", "ask_question", str(FIXTURES / "ask_question_valid.jsonl")]) == 0
    assert "ask_reply_invalid.jsonl:1:" in capsys.readouterr().out
