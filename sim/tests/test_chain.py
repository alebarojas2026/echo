"""The simulated sealed record and its witnesses (sim/chain.py, CONTRACTS.md section 13)."""
import json

import pytest

from contracts import check
from sim import chain, fake, state
from sim.wire import encoder
from store.chain import ZERO, verify_rows

PATHS = ["witnesses", "witness_silent", "chain_broken"]
T0 = 1_763_149_500_000


def feed(name):
    return [e for e in fake.simulate(fake.load_path(name)) if e["type"].startswith("chain_")]


def states(name):
    return [m for m in state.run(fake.load_path(name)) if m["type"] == "state"]


def at(messages, t):
    return next(m for m in messages if m["t"] >= t)


def test_a_path_without_a_chain_block_is_what_it_was():
    assert chain.of(fake.load_path("step_in")) is None
    assert not [e for e in fake.simulate(fake.load_path("step_in")) if e["type"].startswith("chain_")]
    assert all("chain" not in s for s in states("step_in"))


@pytest.mark.parametrize("name", PATHS)
def test_what_the_feed_and_the_brain_send_fits_the_contract(name, each_layout):
    encode = encoder(T0)
    lines = [encode(e) for e in fake.simulate(fake.load_path(name))]
    sent = [json.loads(line) for line in lines if '"type":"chain_' in line]
    assert {m["type"] for m in sent} == {"chain_head", "chain_witness"} and all(m["src"] == "sim" for m in sent)
    assert [e for m in sent for e in check.errors(m)] == []
    with_chain = [s["chain"] for s in states(name)]
    assert all(set(c) == {"seq", "hash8", "verified", "witnesses_ok", "witnesses"} for c in with_chain)
    assert [c["seq"] for c in with_chain] == sorted(c["seq"] for c in with_chain) and with_chain[-1]["seq"] > 30


def test_a_head_every_5_s_signed_by_both_witnesses_and_the_count_rises():
    sent = feed("witnesses")
    heads = [e for e in sent if e["type"] == "chain_head"]
    assert [h["t"] for h in heads] == [0, 5, 10, 15, 20, 25]
    assert [h["seq"] for h in heads] == sorted({h["seq"] for h in heads})        # the head moves on every time
    for head in heads:
        signed = [e for e in sent if e["type"] == "chain_witness" and e["seq"] == head["seq"]]
        assert [(e["node"], e["hash"], e["t"]) for e in signed] == [("pi5", head["hash"], head["t"]), ("pi5b", head["hash"], head["t"])]
    seen = states("witnesses")
    assert at(seen, 12)["chain"]["witnesses_ok"] == 2 and at(seen, 12)["chain"]["witnesses"] == 2
    assert all(s["chain"]["verified"] for s in seen)


def test_the_simulated_chain_really_verifies_and_its_records_fit_the_contract():
    c = chain.of(fake.load_path("witnesses"), T0)
    c.advance(30)
    assert verify_rows(c.rows, ZERO) == (True, len(c.rows), None)
    records = c.records()
    assert [e for r in records for e in check.errors(r, "record")] == []
    assert {r["kind"] for r in records} == {"second", "witness"} and records[0]["t"] == T0
    assert c.verify(30) == {"ok": True, "checked": len(records), "first_bad_seq": None, "ms": 0, "from": 1, "to": len(records)}
    assert check.errors(c.status(30), "chain") == [] and check.errors(c.verify(30), "chain_verify") == []


def test_one_witness_goes_silent_and_comes_back():
    seen = states("witness_silent")
    assert [at(seen, t)["chain"]["witnesses_ok"] for t in (6, 19, 21, 33, 36)] == [2, 2, 1, 1, 2]
    assert all(s["chain"]["witnesses"] == 2 and s["chain"]["verified"] for s in seen)
    signed = [(e["t"], e["node"]) for e in feed("witness_silent") if e["type"] == "chain_witness"]
    assert [t for t, node in signed if node == "pi5b"] == [0, 5, 35, 40]          # nothing from 8 s to 34 s
    assert [t for t, node in signed if node == "pi5"] == [0, 5, 10, 15, 20, 25, 30, 35, 40]
    c = chain.of(fake.load_path("witness_silent"), T0)
    middle = c.status(25)["witnesses"]
    assert middle[1] == {"node": "pi5b", "last_seq": middle[1]["last_seq"], "last_t": T0 + 5000, "sig_ok": True, "silent": True}
    assert middle[0]["silent"] is False and check.errors(c.status(25), "chain") == []
    assert [w["silent"] for w in c.status(45)["witnesses"]] == [False, False]
    marks = [(r["kind"], r["t"] - T0) for r in c.records() if r["kind"] in ("witness_silent", "witness_back")]
    assert marks == [("witness_silent", 20_000), ("witness_back", 35_000)]       # once each; 15 s after its last signature
    assert c.verify(45)["ok"]                                                    # the chain went on


def test_the_check_fails_at_the_named_record():
    seen = states("chain_broken")
    assert [at(seen, t)["chain"]["verified"] for t in (5, 11, 12.5, 25)] == [True, True, False, False]
    assert at(seen, 25)["chain"]["witnesses_ok"] == 2                             # the witnesses keep signing
    c = chain.of(fake.load_path("chain_broken"), T0)
    assert c.status(10)["verified"] is True and c.status(10)["first_bad_seq"] is None
    broken = c.status(20)
    assert (broken["verified"], broken["first_bad_seq"]) == (False, 9) and check.errors(broken, "chain") == []
    result = c.verify(20)
    assert (result["ok"], result["first_bad_seq"], result["checked"]) == (False, 9, 9)
    assert check.errors(result, "chain_verify") == []
    heads = [e for e in feed("chain_broken") if e["type"] == "chain_head"]
    assert [h["verified"] for h in heads] == [True, True, True, False, False, False]


def test_the_command_line_prints_what_the_board_would_answer(capsys):
    chain.main(["witness_silent", "--at", "25"])
    doc = json.loads(capsys.readouterr().out)
    assert check.errors(doc, "chain") == [] and [w["silent"] for w in doc["witnesses"]] == [False, True]
    chain.main(["chain_broken", "--verify"])
    assert json.loads(capsys.readouterr().out)["first_bad_seq"] == 9
    with pytest.raises(SystemExit, match="no chain block"):
        chain.main(["step_in"])


def test_the_store_keeps_a_simulated_path_with_a_chain_like_any_other(tmp_path):
    """state.chain is not part of what the store saves: the store seals its own record."""
    from store import Store
    from store.__main__ import fill_from_sim
    s = Store(tmp_path / "store.db")
    assert fill_from_sim(s, "witnesses", end_ms=T0) > 30
    assert s.verify()["ok"] and "chain" not in s.records(limit=1)[0]["body"]
