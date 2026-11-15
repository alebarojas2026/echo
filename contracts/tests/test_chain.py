"""Section 13: the sealed record, the /chain answers and the witness messages."""
import hashlib
import json
from pathlib import Path

import pytest

from contracts import check

FIXTURES = Path(__file__).parent.parent / "fixtures"
BODIES = ["chain", "chain_verify", "chain_prove", "record"]

BAD = {
    "chain": ["$.head.hash",                # a hash is 64 hex
              "$.verified",                 # true, false or "checking"
              "$.first_bad_seq",            # verified, yet a bad record is named
              "$.first_bad_seq",            # not verified, and no record is named
              "'last_seq' is a required property",
              "$.witnesses[0].node"],       # a witness is a node of the layout
    "chain_verify": ["$.first_bad_seq",     # ok, yet a bad record is named
                     "$.first_bad_seq",     # not ok, and no record is named
                     "'ms' is a required property"],
    "chain_prove": ["$.ok",                 # an altered copy never verifies
                    "'altered_seq' is a required property"],
    "record": ["'hash' is a required property",
               "$.seq",                     # seq starts at 1
               "$.prev",                    # prev is a hash
               "'sig' is a required property",
               "'node' is a required property",
               "$.body.node"],
}


def lines(name):
    return (FIXTURES / name).read_text(encoding="utf-8").splitlines()


def test_the_chain_messages_are_bus_messages_and_the_answers_are_not():
    assert {"chain_head", "chain_witness"} <= set(check.TYPES)
    assert not set(BODIES) & set(check.TYPES)


@pytest.mark.parametrize("schema", BODIES)
def test_valid_chain_bodies_pass(schema):
    count, failures, warnings = check.check_lines(lines(f"{schema}_valid.jsonl"), schema)
    assert count >= 1 and failures == [] and warnings == []


@pytest.mark.parametrize("schema", BODIES)
def test_each_invalid_chain_body_fails_for_its_reason(schema):
    bad = lines(f"{schema}_invalid.jsonl")
    assert len(bad) == len(BAD[schema])
    for no, (line, reason) in enumerate(zip(bad, BAD[schema]), 1):
        failures = check.check_lines([line], schema)[1]
        assert any(reason in err for _, err in failures), f"line {no}: {failures}"


def test_the_command_line_checks_chain_bodies_by_name():
    for schema in BODIES:
        assert check.main(["--as", schema, str(FIXTURES / f"{schema}_valid.jsonl")]) == 0
        assert check.main(["--as", schema, str(FIXTURES / f"{schema}_invalid.jsonl")]) == 1


def test_a_chain_seq_is_a_record_number_so_a_jump_is_not_a_lost_message():
    count, failures, warnings = check.check_lines(lines("valid_chain.jsonl"))
    assert count == 5 and failures == [] and warnings == []


@pytest.mark.parametrize("change, where", [
    ({"hash": "abc"}, "$.hash"),                      # a hash is 64 hex
    ({"sig": "not a signature"}, "$.sig"),
    ({"node": "east2"}, "$.node"),
    ({"extra": 1}, "'extra' was unexpected"),
])
def test_a_bad_witness_message_fails(change, where):
    witness = next(m for m in map(json.loads, lines("valid_chain.jsonl")) if m["type"] == "chain_witness")
    assert check.errors(witness) == []
    assert any(where in e for e in check.errors({**witness, **change}))


@pytest.mark.parametrize("layout", ["desk", "gate"])
def test_the_chain_in_state_is_optional_and_whole_when_there(layout):
    state = json.loads(lines(f"{layout}/valid_state.jsonl")[0])
    on = check.load_layout(layout)
    assert "chain" not in state and check.errors(state, layout=on) == []        # older states stay valid
    chain = {"seq": 4127, "hash8": "1a2b3c4d", "verified": True, "witnesses_ok": 2, "witnesses": 2}
    assert check.errors({**state, "chain": chain}, layout=on) == []
    assert check.errors({**state, "chain": {**chain, "witnesses_ok": 0, "witnesses": 0, "verified": False}}, layout=on) == []
    for bad in ({**chain, "hash8": "1a2b"}, {**chain, "verified": "checking"}, {k: v for k, v in chain.items() if k != "seq"}):
        assert any("$.chain" in e for e in check.errors({**state, "chain": bad}, layout=on))


def test_an_answer_may_show_its_steps_its_records_and_whether_the_chain_held():
    reply = json.loads(lines("ask_reply_valid.jsonl")[0])
    assert check.errors(reply, "ask_reply") == []                                # an older answer stays valid
    more = {**reply, "steps": [{"tool": "records", "ms": 12, "rows": 61}, {"tool": "verify", "ms": 3.5, "rows": 61}],
            "cites": [4012, 4040], "chain_ok": True}
    assert check.errors(more, "ask_reply") == []
    assert any("$.cites[0]" in e for e in check.errors({**more, "cites": [0]}, "ask_reply"))
    assert any("$.steps[0]" in e for e in check.errors({**more, "steps": [{"tool": "records"}]}, "ask_reply"))
    assert any("$.chain_ok" in e for e in check.errors({**more, "chain_ok": "yes"}, "ask_reply"))
    story = {**more, "tool": "story", "rows": [{"text": "Someone stepped in at 18:21:49.", "cites": [4012]}],
             "span": {"from_t": 1763149309000, "to_t": 1763149329000}}
    assert check.errors(story, "ask_reply") == []                                # the detective's own tool
    del story["chain_ok"]                                                        # no sealed record to check: left out
    assert check.errors(story, "ask_reply") == []


def test_the_hash_rule_in_the_contract_is_the_one_python_computes():
    """Section 13 in one place: sorted keys, no spaces, UTF-8 with characters as themselves."""
    record = {"seq": 1, "t": 1763149510000, "kind": "second", "body": {"motion": "still", "present": 1, "note": "café"},
              "prev": "0" * 64}
    canon = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    assert canon == ('{"body":{"motion":"still","note":"café","present":1},"kind":"second",'
                     '"prev":"' + "0" * 64 + '","seq":1,"t":1763149510000}').encode("utf-8")
    sealed = {**record, "hash": hashlib.sha256(canon).hexdigest()}
    assert check.errors(sealed, "record") == []


def test_section_13_names_what_the_schemas_hold():
    text = (Path(check.__file__).parent.parent / "CONTRACTS.md").read_text(encoding="utf-8")
    section = text[text.index("## 13. The sealed record"):]
    for word in ("chain_head", "chain_witness", "witness_silent", "witness_back", "witness_bad", "/chain/verify", "/chain/prove",
                 "hash8", "witnesses_ok", "first_bad_seq", "altered_seq", "last_verify_t", "pkeyutl -verify", "-rawin",
                 "sort_keys=True", "anchor", "unsealed"):
        assert word in section, word
