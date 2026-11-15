"""Proof on one spot and three devices: fixtures/gate-nodes.json, this folder's copy of the gate layout.

One zone, a strip with no split line. The zone score is then the presence score (nobody or at the
desk), and nothing may ask for a left, a right or a line between them."""
import json
import re

import pytest

from proof import ablation, false_alarms, layout
from proof import lesson as L
from proof.score import confusion_report, presence_from_confusion, score, threshold_zone, zone_classes
from proof.security import analyze, hold_seconds
from proof.security_walk import run
from proof.walk import orders, script

SIDES = re.compile(r"\b(left|right|east|west|middle|zone)\b", re.I)
CROSSING = ["pi5b>unoq:ble", "pi5>pi5b:wifi", "pi5>pi5b:ble", "pi5b>pi5:ble"]


def session(name="held", zone=0):
    meta = dict(v=2, type="meta", recv_t=0, t=999999, src="live", session=name, purpose="heldout", walker="w1")
    messages = [meta] + [dict(v=2, type="label", recv_t=t, t=999999 - t, src="live", zone=zone, present=bool(zone),
                              persons_in_frame=int(bool(zone)), mode="person", clipped=False)
                         for t in range(0, 2100, 100)]
    return {"meta": meta, "messages": messages}


class FakeReplay:
    train_sessions = {"train"}
    train_walkers = {"training-walker"}
    train_s = 1.25
    base = {"pi5b>unoq:ble": -58}

    def __init__(self, zones):
        self.zones = zones

    def replay(self, session):
        for i, zone in enumerate(self.zones):
            yield dict(end=1000 + i * 100, pred=None if zone is None else
                       dict(zone=zone or None, present=bool(zone), kind="person" if zone else "none"),
                       links={"pi5b>unoq:ble": {"drop_db": 12 if zone else 0}, "pi5>unoq:ble": {"drop_db": 9}}, ms=2)


def test_the_spot_is_the_strip_and_nothing_asks_for_a_split(gate):
    assert layout.is_strip(gate) and layout.is_spot(gate) and "zone_split_x_m" not in gate["frame"]
    assert layout.zones(gate) == {1: (0.4, 0.3, "At the desk")}
    assert [layout.zone_at(gate, x, y) for x, y in ((0.4, 0.3), (0.0, 0.0), (0.8, 0.59))] == [1, 1, 1]
    # standing back, beside it, or on the desk's side of its edge is not on the spot
    assert [layout.zone_at(gate, x, y) for x, y in ((0.4, -0.1), (0.4, 0.6), (-0.1, 0.3), (0.9, 0.3), (0.4, 0.8))] == [0] * 5


def test_the_threshold_baseline_uses_the_lines_that_cross_the_spot(gate):
    assert layout.link_zones(gate) == {link: 1 for link in CROSSING}
    assert threshold_zone({"pi5b>unoq:ble": {"drop_db": 11.0}, "pi5>unoq:ble": {"drop_db": 1.0}}, doc=gate) == 1
    assert threshold_zone({"pi5b>unoq:ble": {"drop_db": 1.0}, "pi5>unoq:ble": {"drop_db": 9.0}}, doc=gate) == 0   # a desk line never votes
    assert threshold_zone({"pi5>unoq:ble": {"drop_db": 9.0}}, doc=gate) is None
    unmarked = json.loads(json.dumps(gate))
    for link in unmarked["links"]:
        del link["crosses_spot"]
    assert set(layout.link_zones(unmarked)) == set(CROSSING)   # with no marks, the midpoints say the same here


def test_the_zone_score_is_the_presence_score(gate):
    assert zone_classes() == [0, 1]
    details = {}
    result = score([session(zone=1)], FakeReplay((1,) * 9 + (0,) * 2), commit="abc", details=details)
    assert result["zone"]["correct"] == 9 and result["zone"]["total"] == 11
    assert details["confusion"]["classes"] == [0, 1] and details["confusion"]["chance"] == 0.5
    assert details["confusion"]["counts"] == [[0, 0], [2, 9]]
    assert result["presence"]["total"] is not None and result["presence"]["correct"] <= result["presence"]["total"]
    assert result["threshold_zone"] == {"correct": 9, "total": 11}
    assert result["person_vs_object"] == {"correct": 9, "total": 11, "tray_placements": None}


def test_an_empty_heldout_walk_and_no_walk_at_all_score_without_dividing_by_zero(gate):
    result = score([session(zone=0)], FakeReplay((0,) * 11))
    assert result["zone"]["correct"] == result["zone"]["total"] == 11
    assert result["person_vs_object"] == {"correct": None, "total": None, "tray_placements": None}
    nothing = score([session(zone=0)], FakeReplay((None,) * 11))
    assert nothing["zone"] == {**nothing["zone"], "correct": None, "total": None}
    assert presence_from_confusion(confusion_report({}))["total"] is None


def test_the_walk_goes_on_and_off_the_spot_and_names_no_side(gate):
    assert orders(gate)["train"] == (1, "off", 1, "off", 1) and orders(gate)["crowd"] == (1,)
    for purpose in ("train", "heldout", "object", "crowd"):
        steps = script(purpose)
        assert not any(SIDES.search(text) for text, *_ in steps), purpose
        assert steps[0] == ("Nobody inside the spot. Step out completely.", 20, "off", None)
    texts = [text for text, *_ in script("train")]
    assert texts.count("Step onto the spot (at the desk): x=0.4 m, y=0.3 m.") == 3
    assert texts.count("Stand still on the spot.") == 3 and sum("Step back off the spot" in t for t in texts) == 2
    assert [truth for *_, truth in script("crowd") if truth is not None] == [1]
    assert "Place the tray at T1 on the desk, then step back out of the spot." in [t for t, *_ in script("object")]


def test_the_security_walk_and_the_lesson_name_no_side(gate):
    now, prompts = [0], []
    for mode in ("entries", "passes"):
        run("trial", "w1", mode, gate, lambda m: None, prompts.append,
            lambda s: now.__setitem__(0, now[0] + s), lambda: now[0], repeats=1)
    said = "\n".join(prompts)
    assert "Step onto the marked spot and stand there." in said
    assert "Walk straight through the spot and leave without stopping; stay inside less than 3 s." in said
    assert not SIDES.search(said) and hold_seconds(gate) == 3
    assert L.one_spot() and L.KEEP_GOING[True] == "Keep stepping on and off the spot"


def test_the_still_limit_and_the_device_subsets_come_from_the_file(gate):
    assert false_alarms.load_zones() == {1: 10}
    groups = {name: (nodes, links) for name, nodes, links in ablation.subsets(gate)}
    assert groups["all"] == (["unoq", "pi5", "pi5b"], [link["id"] for link in gate["links"]])
    assert groups["router_receiver"] == (["pi5", "unoq"], ["pi5>unoq:wifi", "pi5>unoq:ble"])
    assert groups["four_nodes"] == ([], [])   # there are only three


def test_entries_onto_the_spot_are_scored_as_presence(gate):
    report = analyze([], gate)
    assert report["detection"]["entries"] is None and report["false_alarms"]["presence_events"] is None
