import json
from pathlib import Path

import pytest

from contracts import check

FIXTURES = Path(__file__).parent.parent / "fixtures"

# What each line of fixtures/invalid.jsonl gets wrong, in order.
INVALID = [
    "'v' is a required property",   # old sim format
    "$.v",                          # v1
    "$.t",                          # t in seconds, not epoch ms
    "$.link",                       # no such link
    "$.kind",                       # link says wifi, kind says ble
    "'rssi' was unexpected",        # field not in the contract
    "$.zone",                       # clipped but zone set
    "$.motion",                     # nobody there but motion set
    "$.state",                      # cam state paused
    "$.text",                       # more than 16 words
    "$.text",                       # a recap of 50 words, more than 45
    "$.model",                      # llm sentence without a model
    "$.pred.probs",                 # 4 probs, not 5
    "w*h is 25",                    # xray size does not match w x h
    "$.links",                      # links is [] before readings, never null
    "$.links[0].dbm",               # a listed link always has a reading
    "$.links[0].status",            # blind before the baseline
    "$.alert.zone",                 # counting with no zone
    "$.model.ver",                  # trained but no version
    "$.motion",                     # clipped but motion set
    "$.pred.motion",                # nobody there but motion set
    "$.pred.zone",                  # nobody there but zone 3
    "$.pred.zone_set",              # nobody there but zone_set [3]
    "$.objects[0].near",            # east is 1 m away
    "$.advice.before_dbm",           # shown before the router moves, so already measured
    "$.kind",                       # unknown event kind
    "$.args.mode",
    "unknown type 'ping'",
    "bad JSON",
]


def read(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_every_message_type_has_a_schema():
    assert check.TYPES == ["cam", "cmd", "event", "label", "meta", "narration", "rssi", "state"]
    assert "proof" in check.VALIDATORS


@pytest.mark.parametrize("name", sorted(p.name for p in FIXTURES.glob("valid_*.jsonl")))
def test_valid_fixtures_pass(name):
    count, failures, warnings = check.check_lines(read(name).splitlines())
    assert count >= 1 and failures == [] and warnings == []


def test_each_invalid_line_fails_for_its_reason():
    lines = read("invalid.jsonl").splitlines()
    assert len(lines) == len(INVALID)
    for no, (line, reason) in enumerate(zip(lines, INVALID), 1):
        failures = check.check_lines([line])[1]
        assert any(reason in err for _, err in failures), f"line {no}: {failures}"


def test_proof():
    assert check.check_lines([read("valid_proof.json")], "proof")[1] == []
    assert "$.zone.correct" in check.check_lines([read("invalid_proof.json")], "proof")[1][0][1]


def rssi(seq, rx="pi5"):
    link = "east>pi5:ble" if rx == "pi5" else "east>unoq:ble"
    return json.dumps({"v": 2, "type": "rssi", "t": 1763149512120 + seq, "seq": seq, "src": "live",
                       "link": link, "kind": "ble", "tx": "east", "rx": rx, "dbm": -61})


def test_seq_gaps_are_warnings_per_producer():
    count, failures, warnings = check.check_lines([rssi(1), rssi(7, "unoq"), rssi(2), rssi(5), rssi(8, "unoq")])
    assert (count, failures) == (5, [])
    assert warnings == [(4, "live/rssi/pi5/ble: seq 2 -> 5")]


def test_one_counter_for_everything_is_not_a_gap():
    assert check.check_lines([rssi(1), rssi(2, "unoq"), rssi(3), rssi(4, "unoq")])[2] == []


def test_empty_input_fails():
    assert check.check_lines(["", "  "])[1] == [(0, "no messages")]


def test_exit_code(capsys):
    assert check.main([str(p) for p in sorted(FIXTURES.glob("valid*"))]) == 0
    assert check.main([str(FIXTURES / "invalid.jsonl")]) == 1
    assert "invalid.jsonl:1:" in capsys.readouterr().out
