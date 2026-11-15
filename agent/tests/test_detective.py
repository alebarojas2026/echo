"""The detective: "what happened?" told from the stored records, on the one-spot (gate) layout and the desk strip.

The store is filled by the simulated feed in a child process pinned to a layout file (RADIO_SIGHT_NODES), so
these tests hold whichever layout radio/nodes.json is. The sealed record (#866 section 1) is not on main yet:
`Sealed` below stands in for it, with seq, prev and hash as #866 words them and a verify(from_seq, to_seq)."""
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from agent import ask as A
from agent import detective
from contracts import check
from narrator.story import hm
from store import Store

REPO = Path(__file__).resolve().parents[2]
GATE, DESK = REPO / "radio" / "layouts" / "gate.json", REPO / "radio" / "layouts" / "desk.json"
T0 = 1_763_200_020_000
NOW = T0 + 1_100_000
FILL = ("import sys\nfrom store import Store\nfrom store.__main__ import fill_from_sim\ns = Store(sys.argv[1])\n"
        "for p, e in zip(sys.argv[2::2], sys.argv[3::2]):\n    fill_from_sim(s, p, end_ms=int(e))\ns.close()\n")
# A visit with a still stretch, two walk-throughs, a tamper while armed, a quiet empty stretch and a thing left
# in the Wi-Fi line, two to three minutes apart. Nothing is recorded from 8 to 14 minutes but the empty room.
PATHS = [("stand_still", T0 + 60_000), ("passed_by", T0 + 180_000), ("passed_by", T0 + 300_000),
         ("tamper", T0 + 480_000), ("empty_room", T0 + 900_000), ("thing_left", T0 + 1_080_000)]


def filled(tmp_path_factory, layout, paths):
    db = tmp_path_factory.mktemp("store") / "store.db"
    args = [str(db)] + [str(v) for p in paths for v in p]
    subprocess.run([sys.executable, "-c", FILL] + args, cwd=REPO, check=True,
                   env={**os.environ, "RADIO_SIGHT_NODES": str(layout), "PYTHONPATH": str(REPO)})
    return Store(db)


def _hash(rec):
    doc = {k: rec[k] for k in ("seq", "t", "kind", "body", "prev")}
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Sealed:
    """A store whose records carry seq, prev and hash (#866 section 1), with the store's verify function."""

    def __init__(self, store):
        self.store, self.log, self.seq = store, [], {}
        recs = [("s", r) for r in store.seconds(0)] + [("e", e) for e in store.events(0)]
        prev = "0" * 64
        for i, (table, r) in enumerate(sorted(recs, key=lambda x: (x[1]["t"], x[0] == "e")), 1):
            rec = {"seq": i, "t": r["t"], "kind": r["kind"] if table == "e" else "second", "body": r, "prev": prev}
            rec["hash"] = prev = _hash(rec)
            self.log.append(rec)
            self.seq[self._key(table, r)] = i

    @staticmethod
    def _key(table, r):
        return (table, r["t"]) + ((r["kind"], r["id"]) if table == "e" else ())

    def seconds(self, *a):
        return [{**r, "seq": self.seq[self._key("s", r)]} for r in self.store.seconds(*a)]

    def events(self, *a):
        return [{**e, "seq": self.seq[self._key("e", e)]} for e in self.store.events(*a)]

    def latest(self):
        return self.store.latest()

    def verify(self, from_seq, to_seq):
        self.asked = (from_seq, to_seq)
        prev = self.log[from_seq - 2]["hash"] if from_seq > 1 else "0" * 64
        for rec in self.log[from_seq - 1:to_seq]:
            if rec["prev"] != prev or _hash(rec) != rec["hash"]:
                return {"ok": False, "checked": rec["seq"] - from_seq + 1, "first_bad_seq": rec["seq"], "ms": 0}
            prev = rec["hash"]
        return {"ok": True, "checked": to_seq - from_seq + 1, "first_bad_seq": None, "ms": 0}


@pytest.fixture(scope="module")
def gate(tmp_path_factory):
    store = filled(tmp_path_factory, GATE, PATHS)
    yield store
    store.close()


def zones(path):
    return A.layout(path)


def asked(store, question, path=GATE, now_ms=NOW, **kw):
    z, links = zones(path)
    return A.ask(question, store, now_ms=now_ms, zones=z, links=links, nodes_path=path, **kw)


# What section 13 (the contract branch for #866) adds to POST /ask's reply, plus the tool "story" asked for on #866.
ADDED = {"steps": {"type": "array", "minItems": 1, "items": {
            "type": "object", "required": ["tool", "ms", "rows"], "additionalProperties": False,
            "properties": {"tool": {"type": "string", "minLength": 1}, "ms": {"type": "number", "minimum": 0},
                           "rows": {"type": "integer", "minimum": 0}}}},
         "cites": {"type": "array", "items": {"type": "integer", "minimum": 1}},
         "chain_ok": {"type": "boolean"}}


def story_errors(reply):
    schemas = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in check.SCHEMAS.glob("*.json")}
    schema = copy.deepcopy(schemas["ask_reply"])
    schema["$id"] += "-866"
    schema["properties"]["tool"]["enum"].append("story")
    schema["properties"].update(ADDED)
    registry = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in schemas.values())
    out = [e.message for e in Draft202012Validator(schema, registry=registry).iter_errors(reply)]
    return out + ([] if "steps" in reply else ["steps"]) + ([] if ("cites" in reply) == ("chain_ok" in reply) else ["cites"])


def sentences(reply):
    return [r for r in reply["rows"] if r.get("row") == "sentence"]


def test_the_story_of_the_gate_tells_each_thing_once_in_time_order_with_clock_times(gate):
    sealed = Sealed(gate)
    reply = asked(sealed, "what happened in the last 20 minutes?")
    assert reply["tool"] == "story" and reply["picked_by"] == "rules" and story_errors(reply) == []
    lines = sentences(reply)
    assert [r["t"] for r in lines] == sorted(r["t"] for r in lines)
    text = reply["answer"]
    still = [r for r in gate.seconds(T0, T0 + 60_000) if r["present"] == 1 and r["motion"] == "still"]
    assert f"Somebody stepped in at the desk and stood still for {len(still)} seconds." in text
    assert text.count("Somebody walked through at the desk.") == 2
    tamper, back = [e["t"] for e in gate.events(0, ("tamper", "tamper_cleared"))]
    assert f"Pi B went quiet for {round((back - tamper) / 1000)} seconds while the space was armed." in text
    assert "Something was left in the Wi-Fi line" in text
    assert text.startswith(hm(lines[0]["t"]) + ". ")
    at = 0
    for line in lines:   # every sentence is said, in order, after the clock time of its minute
        found = text.index(line["text"], at)
        assert line["cites"] and text.rindex(line["at"] + ".", 0, found) >= 0
        at = found + len(line["text"])
    # Nothing a person can't be told: no sides, no identity, no camera.
    assert not re.search(r"\bon the (left|right)\b|\b(he|she|camera|man|woman)\b", text, re.I)


def test_the_answer_shows_its_steps_cites_records_and_verifies_the_cited_range(gate):
    sealed = Sealed(gate)
    reply = asked(sealed, "what happened in the last 20 minutes?")
    assert [s["tool"] for s in reply["steps"]] == ["fetch events", "fetch summaries", "line up the timeline",
                                                   "verify the chain", "write the story"]
    in_range = [r["seq"] for r in sealed.events(NOW - 20 * 60_000) + sealed.seconds(NOW - 20 * 60_000, NOW)]
    assert reply["steps"][0]["rows"] + reply["steps"][1]["rows"] == len(in_range)
    assert reply["steps"][2]["rows"] == len(sentences(reply))
    assert reply["cites"] == sorted({c for r in sentences(reply) for c in r["cites"]})
    assert set(reply["cites"]) <= set(in_range)
    assert sealed.asked == (reply["cites"][0], reply["cites"][-1]) and reply["chain_ok"] is True
    assert reply["steps"][3]["rows"] == reply["cites"][-1] - reply["cites"][0] + 1
    assert not reply["answer"].startswith("Warning")


def test_a_broken_chain_is_said_first_and_names_the_record(gate):
    sealed = Sealed(gate)
    good = asked(sealed, "tell me the story of the last 20 minutes")
    bad = good["cites"][len(good["cites"]) // 2]
    sealed.log[bad - 1]["body"] = {**sealed.log[bad - 1]["body"], "present": 0}   # edited after it was sealed
    reply = asked(sealed, "tell me the story of the last 20 minutes")
    assert reply["chain_ok"] is False and story_errors(reply) == []
    assert reply["answer"].startswith(f"Warning: the sealed record does not check out at record {bad}, ")
    assert good["answer"] in reply["answer"]   # the story is still told, after the warning


def test_an_empty_stretch_is_said_plainly(gate):
    z, _ = zones(GATE)
    quiet = detective.investigate(gate, T0 + 872_000, T0 + 898_000, z, {})
    unknown = sum(r["present"] is None for r in gate.seconds(T0 + 872_000, T0 + 898_000))
    note = f" For {unknown} second{'s' if unknown > 1 else ''} of it the sensor could not tell." if unknown else ""
    assert quiet["answer"] == f"Nothing happened between {hm(T0 + 872_000)} and {hm(T0 + 898_000)}. Nobody was seen.{note}"
    gap = asked(gate, "what happened in the last 3 minutes?", now_ms=T0 + 840_000)
    assert gap["answer"] == f"I have no records between {hm(T0 + 660_000)} and {hm(T0 + 840_000)}."
    assert sentences(gap) == [] and "chain_ok" not in gap and story_errors(gap) == []


@pytest.mark.skipif(hasattr(Store, "verify"), reason="the store seals every record")
def test_without_a_sealed_record_it_cites_record_times_and_does_not_claim_a_check(gate):
    reply = asked(gate, "what happened?")
    assert "chain_ok" not in reply and "cites" not in reply
    cited = {c for r in sentences(reply) for c in r["cites"]}
    assert cited and cited <= {f"t{r['t']}" for r in gate.seconds(0) + gate.events(0)}
    assert reply["steps"][3] == {"tool": "verify the chain", "ms": reply["steps"][3]["ms"], "rows": 0}
    assert story_errors(reply) == []


def test_the_keyword_path_never_waits_on_the_model_and_answers_well_under_a_second(gate):
    def slow(*_):
        raise AssertionError("the model was asked")
    reply = asked(Sealed(gate), "what happened in the last 20 minutes?", llm=slow)
    assert reply["picked_by"] == "rules" and reply["ms"] < 1000


def test_a_writer_may_only_smooth_the_wording(gate):
    sealed = Sealed(gate)
    plain = asked(sealed, "what happened in the last 20 minutes?")["answer"]
    smooth = asked(sealed, "what happened in the last 20 minutes?", writer=lambda m: m[-1]["content"].replace("Somebody", "Someone"))
    assert smooth["answer"] == plain.replace("Somebody", "Someone")
    assert smooth["steps"][-1]["tool"] == "write the story and smooth it"
    changed = asked(sealed, "what happened in the last 20 minutes?", writer=lambda m: m[-1]["content"].replace("seconds", "0 seconds", 1))
    assert changed["answer"] == plain


@pytest.mark.parametrize("question", [
    "What happened?", "what just happened", "What happened in the last 5 minutes?", "what has happened since 2?",
    "What happened between 2:10 and 2:20?", "Who was here?", "who came by?", "Tell me the story", "Replay it",
    "what did the board see?", "what went on?"])
def test_story_questions_go_to_the_detective(gate, question):
    reply = asked(gate, question)
    assert reply["tool"] == "story" and reply["picked_by"] == "rules", reply["answer"]
    assert reply["answer"].startswith("I can't tell who anyone is") == bool(re.search(r"who", question, re.I))


@pytest.mark.parametrize("question, tool", [
    ("was anyone here in the last 10 minutes?", "presence"), ("What is happening at the desk?", "presence"),
    ("Are you recording me?", "model_card"), ("Is anything blocking the Wi-Fi?", "explain_advice"),
    ("Is the room armed?", "intrusions"), ("Who was that?", None), ("who was here and what is her name?", None),
    ("how many people were here?", None)])
def test_the_other_questions_keep_their_tools(gate, question, tool):
    reply = asked(gate, question, privacy_reader=lambda **kw: {"ok": False, "why": "test"})
    assert reply["tool"] == tool and "steps" not in reply


def test_the_privacy_answer_says_a_clock_time_not_an_epoch(gate):
    meter = {"ok": True, "images": 0, "bytes_out": 0, "since_t": NOW - 600_000, "t": NOW}
    reply = asked(gate, "Is anything sent to the internet?", privacy_reader=lambda **kw: meter)
    assert f"0 images stored and 0 internet bytes out since {hm(NOW - 600_000)}." in reply["answer"]
    assert "epoch" not in reply["answer"] and reply["rows"][0]["since"] == hm(NOW - 600_000)
    assert check.errors(reply, "ask_reply") == []


def test_between_two_clock_times_is_the_latest_such_stretch():
    now = T0
    tm_now = hm(now)
    frm, to = detective.between_said(f"what happened between {tm_now} and {tm_now}", now)
    assert hm(frm) == tm_now and frm <= now and to == now
    assert detective.between_said("between 25:00 and 2", now) is None
    a, b = detective.between_said("what happened from 1 to 2 am", now + 86_400_000)
    assert hm(a) == "1:00 AM" and hm(b) == "2:00 AM" and b - a == 3_600_000 + 59_999


@pytest.mark.skipif(not hasattr(Store, "verify"), reason="the store does not seal records yet")
def test_on_the_real_sealed_store_the_chain_is_checked_and_an_edit_is_named(gate):
    reply = asked(gate, "what happened in the last 20 minutes?")
    assert reply["chain_ok"] is True and reply["cites"] and story_errors(reply) == []
    bad = reply["cites"][len(reply["cites"]) // 2]
    gate.db.execute("update chain set body = replace(body, '\"present\": 0', '\"present\": 1') where seq = ?", (bad,))
    gate.db.execute("update chain set t = t + 1 where seq = ?", (bad,))
    broken = asked(gate, "what happened in the last 20 minutes?")
    gate.db.execute("update chain set t = t - 1 where seq = ?", (bad,))
    assert broken["chain_ok"] is False and broken["answer"].startswith(f"Warning: the sealed record does not check out at record {bad}, ")


def test_the_desk_strip_still_gets_its_story_with_its_sides(tmp_path_factory):
    store = filled(tmp_path_factory, DESK, [("step_in", T0 + 60_000)])
    reply = asked(store, "what happened?", path=DESK, now_ms=T0 + 70_000)
    assert reply["tool"] == "story" and story_errors(reply) == []
    assert re.search(r"Somebody stepped in on the (left|right)", reply["answer"]), reply["answer"]
    store.close()
