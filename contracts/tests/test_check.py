import json
from pathlib import Path

import pytest

from contracts import check

FIXTURES = Path(__file__).parent.parent / "fixtures"
DESK = check.load_layout("desk")   # the fixtures in fixtures/ itself were written on the desk layout
# fixtures/<layout>/ holds the fixtures that only one layout can pass: states, whose probs and near follow it
VALID = sorted(p.relative_to(FIXTURES).as_posix() for p in FIXTURES.rglob("valid_*.jsonl"))

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
    "$.pred.probs",                 # 5 probs, the old four-zone shape: the desk has two zones, so [empty, z1, z2]
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
    "'node' is a required property",   # a tamper names its node
    "$.info.node",                  # no such node
    "$.info.node",                  # a hall beacon is a node only for tamper
    "$.tamper[1]",                  # no such node
    "$.tamper",                     # tamper is a list of nodes
    "$.tamper",                     # a node is listed once
    "'zone' is a required property",   # a passed_by names its zone
    "$.info.zone",                  # nobody passes by in zone 0
    "$.hall[0].moving",             # a busy path never says moving
    "$.hall[0].busy",               # a stale path is not busy
    "$.hall[0].busy",               # busy is true or false
    "bad JSON",
]


def read(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_every_message_type_has_a_schema():
    assert check.TYPES == ["cam", "chain_head", "chain_witness", "cmd", "event", "label", "meta", "narration", "rssi", "state"]
    assert "proof" in check.VALIDATORS


@pytest.mark.parametrize("name", VALID)
def test_valid_fixtures_pass(name):
    layout = check.layout_of(FIXTURES / name) or DESK
    count, failures, warnings = check.check_lines(read(name).splitlines(), layout=layout)
    assert count >= 1 and failures == [] and warnings == []


def test_every_layout_with_its_own_states_has_them_in_its_own_folder():
    assert "desk/valid_state.jsonl" in VALID and "gate/valid_state.jsonl" in VALID
    assert not (FIXTURES / "valid_state.jsonl").exists()
    assert check.layout_of(FIXTURES / "gate" / "valid_state.jsonl")["layout"] == "gate"
    assert check.layout_of(FIXTURES / "valid_rssi.jsonl") is None      # the layout in use


def test_a_state_of_one_layout_fails_on_another():
    desk_on_gate = check.check_lines(read("desk/valid_state.jsonl").splitlines(), layout=check.load_layout("gate"))[1]
    gate_on_desk = check.check_lines(read("gate/valid_state.jsonl").splitlines(), layout=DESK)[1]
    assert any("$.pred.probs: has 3 entries, but this layout has 1 zone:" in e for _, e in desk_on_gate)
    assert any("$.pred.probs: has 2 entries, but this layout has 2 zones:" in e for _, e in gate_on_desk)


def test_one_zone_states_say_empty_then_the_spot_and_a_thing_in_the_line_moves_no_router():
    states = [json.loads(line) for line in read("gate/valid_state.jsonl").splitlines()]
    preds = [s["pred"] for s in states]
    assert all(len(p["probs"]) == 2 for p in preds)
    assert all(p["zone"] == 1 and p["zone_set"] == [1] for p in preds if p["present"])
    thing = next(s for s in states if s["pred"]["kind"] == "object")
    assert thing["pred"]["present"] is False and thing["pred"]["zone"] == 0
    advice = thing["advice"]
    assert (advice["to_spot"], advice["move_m"], advice["dist_change_m"], advice["after_dbm"]) == (None, [0, 0], 0, None)
    cleared = next(s["advice"] for s in states if s["advice"] and s["advice"]["after_dbm"] is not None)
    assert cleared["after_dbm"] > cleared["before_dbm"] and cleared["to_spot"] is None   # the gain, in the fields it always had
    gate = check.load_layout("gate")
    for move in ({"move_m": [-0.3, 0]}, {"dist_change_m": 0.1}):
        bad = {**thing, "advice": {**advice, **move}}
        assert any("$.advice.move_m" in e for e in check.errors(bad, layout=gate))
    assert check.errors({**thing, "advice": {**advice, "to_spot": "S-home"}}, layout=gate)   # home is never a target


def test_each_invalid_line_fails_for_its_reason():
    lines = read("invalid.jsonl").splitlines()
    assert len(lines) == len(INVALID)
    for no, (line, reason) in enumerate(zip(lines, INVALID), 1):
        failures = check.check_lines([line], layout=DESK)[1]
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


def test_not_sure_where_is_every_zone_in_zone_set():
    not_sure = [json.loads(line)["pred"] for line in read("desk/valid_state.jsonl").splitlines()]
    not_sure = [p for p in not_sure if p and len(p["zone_set"]) > 1]
    assert not_sure and all(p["present"] and p["zone_set"] == [1, 2] and p["zone"] in (1, 2) for p in not_sure)


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
    assert check.main([str(FIXTURES / name) for name in VALID]) == 0     # each in its layout's folder, whichever is in use
    assert check.main(["--layout", "desk", str(FIXTURES / "invalid.jsonl")]) == 1
    assert "invalid.jsonl:1:" in capsys.readouterr().out
    assert check.main(["--layout", "desk", str(FIXTURES / "gate" / "valid_state.jsonl")]) == 1
    assert check.main(["--layout", "gate", str(FIXTURES / "gate" / "valid_state.jsonl")]) == 0
