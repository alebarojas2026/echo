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
    "$.pred.probs",                 # 5 probs, the old four-zone shape: it is [empty, z1, z2] now
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
    "$.objects[0].near",            # east is 0.8 m away
    "$.advice.before_dbm",           # shown before the router moves, so already measured
    "$.kind",                       # unknown event kind
    "$.args.mode",
    "unknown type 'ping'",
    "$.zone",                       # zone 3: the desk layout has zones 1 and 2 only
    "$.rx",                         # pi5>pi5b:wifi is heard by pi5b, not by the board
    "$.alert.zone",                 # an alert in zone 4
    "$.objects[0].near",            # the old tray spot: on the desk layout the board is the closest node, not pi5
    "$.pred.why[0]",                # a hall link is never a core link
    "$.args.keep_model",            # keep_model is true or false
    "$.link",                       # a hall beacon heard by east, which is not a receiver
    "$.tx",                         # the link says beacon h, tx says j
    "$.hall[0].activity",           # activity is 0-1
    "$.hall[0].moving",             # a stale hall link is never moving
    "$.hall[0].id",                 # a core link in the hall list
    "$.armed",                      # armed is true or false
    "'on' is a required property",   # arm says on or off
    "$.info",                       # an intrusion names a zone or a hall link
    "$.info",                       # an intrusion is never in zone 0
    "$.model.training.lesson.of",   # the learning signal counts 10 decisions at most
    "7 of 5",                       # more agreeing decisions than decisions
    "'fitting' is a required property",   # a lesson says whether a fit is running
    "$.model.training",             # a lesson without the fit block around it
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


def test_proof_security_is_optional_and_names_real_links():
    proof = json.loads(read("valid_proof.json"))
    assert proof["security"]["detection"]["within_s"] == 2
    del proof["security"]                                       # the whole object may be missing
    assert check.check_lines([json.dumps(proof)], "proof")[1] == []
    errors = check.check_lines([read("invalid_proof_security.json")], "proof")[1]
    assert "$.security.fewer_devices[0].links[0]" in errors[0][1]   # not a link in nodes.json


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
