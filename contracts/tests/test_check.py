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
    "$.src",
    "$.link",                       # no such link
    "$.kind",                       # link says wifi, kind says ble
    "'rssi' was unexpected",        # field not in the contract
    "$.zone",                       # clipped but zone set
    "'conf' is a required property",
    "$.state",                      # cam state paused
    "$.text",                       # more than 16 words
    "$.purpose",
    "$.pred.probs",                 # 4 probs, not 5
    "$.health.status",
    "w*h is 25",                    # xray size does not match w x h
    "$.kind",                       # unknown event kind
    "$.args.mode",
    "$.cmd",
    "unknown type 'ping'",
    "bad JSON",
]


def test_every_message_type_has_a_schema():
    assert check.TYPES == ["cam", "cmd", "event", "label", "meta", "narration", "rssi", "state"]
    assert "proof" in check.VALIDATORS


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("valid_*.jsonl")), ids=lambda p: p.stem)
def test_valid_fixtures_pass(path):
    count, failures, warnings = check.check_lines(path.read_text(encoding="utf-8").splitlines())
    assert count >= 1
    assert failures == []
    assert warnings == []


def test_valid_proof_passes():
    assert check.check_proof((FIXTURES / "valid_proof.json").read_text(encoding="utf-8")) == []


def test_each_invalid_line_fails_for_its_reason():
    lines = (FIXTURES / "invalid.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(INVALID)
    for no, (line, reason) in enumerate(zip(lines, INVALID), 1):
        _, failures, _ = check.check_lines([line])
        assert failures, f"line {no} passed"
        assert any(reason in err for _, err in failures), f"line {no}: {failures}"


def test_invalid_proof_fails():
    errs = check.check_proof((FIXTURES / "invalid_proof.json").read_text(encoding="utf-8"))
    assert any("$.zone.correct" in e for e in errs)


def rssi(seq, rx="pi5"):
    link, tx = ("east>pi5:ble", "east") if rx == "pi5" else ("east>unoq:ble", "east")
    return json.dumps({"v": 2, "type": "rssi", "t": 1763149512120 + seq, "seq": seq, "src": "live",
                       "link": link, "kind": "ble", "tx": tx, "rx": rx, "dbm": -61})


def test_seq_gaps_are_warnings_per_producer():
    lines = [rssi(1), rssi(7, rx="unoq"), rssi(2), rssi(5), rssi(8, rx="unoq")]
    count, failures, warnings = check.check_lines(lines)
    assert (count, failures) == (5, [])
    assert warnings == [(4, "live/rssi/pi5/ble: seq 2 -> 5 (2 lost)")]


def test_empty_input_fails():
    assert check.check_lines(["", "  "])[1] == [(0, "no messages")]


def test_exit_code(capsys):
    assert check.main([str(p) for p in sorted(FIXTURES.glob("valid*"))]) == 0
    assert check.main([str(FIXTURES / "invalid.jsonl")]) == 1
    assert "invalid.jsonl:1:" in capsys.readouterr().out
