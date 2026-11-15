"""The whole brain on the gate layout: three devices, six links, one spot (gate_nodes.json here).

The feed is made up (brain/tests/gatefeed.py), shaped like what the kit gave: about 6 readings
a second on the lines to Pi B (one at 2), a 2 to 5 dB wobble with nobody there, a 10 to 14 dB
drop with a person on the spot. It shows the rules hold at those numbers. It is not a
measurement of the real desk.
"""
import statistics

import pytest

from brain.core import Brain
from brain.tests.gatefeed import GATE, LINKS, Feed
from brain.tests.simdata import T0_MS
from brain.tests.test_core import cmd
from brain.xray import Xray, grid_shape, zone_rule
from contracts import check

LESSON = [(6, "nobody"), (8, "moving"), (8, "still"), (5, "nobody"), (5, "shift"), (4, "nobody")]   # 36 s


class Kit:
    """A brain on the gate layout with the made-up feed playing into it."""

    def __init__(self, seed=0, wobble_db=1.2):
        self.brain, self.feed = Brain(nodes=GATE), Feed(T0_MS, seed, wobble_db)
        self.rows, self.events, self._last = [], [], 0

    def _send(self, msg):
        self.brain.on_message(msg)
        if msg["recv_t"] - self._last >= 100:    # the live loop takes state ten times a second
            self._last = msg["recv_t"]
            self.rows.append((msg["recv_t"], self.brain.state()))
            self.events += [(msg["recv_t"], e) for e in self.brain.pop_events()]

    def play(self, plan, camera=False):
        """Plays the plan and returns (its start in ms, the states taken, the events sent) for it alone."""
        start, rows, events = self.feed.t, len(self.rows), len(self.events)
        self.feed.play(plan, camera=camera, send=self._send)
        return start, self.rows[rows:], self.events[events:]

    def teach(self):
        self.brain.on_cmd(cmd("baseline"))
        self.play([(26, "nobody")], camera=True)
        assert [e["kind"] for _, e in self.events if e["kind"] == "baseline_done"] == ["baseline_done"]
        self.brain.on_cmd(cmd("record_start", session="g1", purpose="train", walker="w1"))
        self.brain.on_message({"v": 2, "type": "meta", "t": int(self.feed.t), "recv_t": int(self.feed.t),
                               "session": "g1", "purpose": "train", "walker": "w1"})
        self.play(LESSON, camera=True)
        self.brain.on_cmd(cmd("record_stop"))
        self.brain.on_cmd(cmd("train"))
        assert self.brain.model is not None and self.brain.model.trained
        return self


def comings(events):
    return [e["kind"] for _, e in events if e["kind"] in ("enter", "exit", "zone_change")]


def when(events, kind):
    return next(t for t, e in events if e["kind"] == kind)


@pytest.fixture(scope="module")
def kit():
    return Kit().teach()


def test_the_layout_gives_six_links_one_zone_a_grid_and_a_rule():
    brain = Brain(nodes=GATE)
    assert brain.links == tuple(LINKS) and brain.zone_ids == [1] and brain.router_node == "pi5"
    # Pi A's links: every one but pi5b>unoq:ble
    assert brain.router_links == [k for k in LINKS if k != "pi5b>unoq:ble"]
    # the two Pi B hears come over the hotspot and never blind the sensor
    assert list(brain.health.classifier_links) == ["pi5>unoq:wifi", "pi5>unoq:ble", "pi5b>unoq:ble", "pi5b>pi5:ble"]
    zone = zone_rule(GATE)
    assert [zone(0.4, 0.3), zone(0.0, 0.0), zone(0.8, 0.6)] == [1, 1, 1]
    assert [zone(0.4, -0.1), zone(0.4, 0.7), zone(-0.1, 0.3), zone(0.9, 0.3)] == [0, 0, 0, 0]   # standing back is not on the spot
    xray = Xray.from_nodes(GATE)
    assert grid_shape(GATE["frame"]) == (10, 14)
    assert (xray.grid.w, xray.grid.h, round(xray.grid.cell_m, 4)) == (10, 14, 0.125)
    assert [round(v, 4) for v in xray.grid.origin_m] == [-0.2, -0.2] and xray.W.shape == (6, 140)
    assert xray.nodes["pi5b"] == (0.4, -0.2)     # a device may sit outside frame.size_m


def test_the_model_has_two_classes_and_probs_is_empty_then_the_spot(kit):
    assert kit.brain.model.classes == [0, 1] and len(kit.brain.model.features) == 6 * 4 + 4 + 1   # and the four crossing lines' medians, and their average
    _, rows, _ = kit.play([(5, "still")])
    pred = rows[-1][1]["pred"]
    assert pred["present"] is True and pred["zone"] == 1 and pred["zone_set"] == [1] and pred["kind"] == "person"
    assert len(pred["probs"]) == 2 and abs(sum(pred["probs"]) - 1) < 0.01 and pred["probs"][1] > 0.5
    assert set(pred["why"]) <= {"pi5b>unoq:ble", "pi5>pi5b:ble", "pi5b>pi5:ble"}    # the lines that cross the spot
    _, rows, _ = kit.play([(5, "nobody")])
    pred = rows[-1][1]["pred"]
    assert (pred["present"], pred["zone"], pred["zone_set"], pred["motion"], len(pred["probs"])) == (False, 0, [], None, 2)
    state = rows[-1][1]
    assert [row["id"] for row in state["links"]] == LINKS and state["health"]["status"] == "ok"
    assert state["xray"]["w"] == 10 and state["xray"]["h"] == 14 and state["xray"]["n_links"] == 6
    # the state passes the schema, apart from the length of probs where the schema is still pinned to two zones
    assert [e for e in check.errors(state) if "probs" not in e] == []


def test_stepping_on_is_found_within_a_second_and_a_half_and_released_within_two(kit):
    found, released = [], []
    for i in range(10):
        start, rows, events = kit.play([(6, ("still", "shift", "moving")[i % 3])])
        assert [e["kind"] for _, e in events] == ["enter"], i
        found.append((events[0][0] - start) / 1000)
        held = [s["pred"]["present"] for t, s in rows if t - start > 2000]
        assert sum(held) >= 0.95 * len(held)                                      # and held: no exit, hardly a flicker
        start, rows, events = kit.play([(5, "nobody")])
        assert [e["kind"] for _, e in events] == ["exit"], i
        released.append((events[0][0] - start) / 1000)
        assert not any(s["pred"]["present"] for t, s in rows if t - start > 2500)
    assert max(found) <= 1.5 and max(released) <= 2.0, (found, released)
    assert statistics.median(found) <= 1.2


def test_ten_minutes_of_an_empty_spot_show_nobody(kit):
    _, rows, events = kit.play([(600, "nobody")])
    assert len(rows) > 5000 and all(s["pred"] is not None for _, s in rows)       # never blind, never unknown
    assert [e["kind"] for _, e in events] == []                                   # no enter, nothing else
    assert sum(s["pred"]["present"] for _, s in rows) <= 2                        # not even a flicker held


def test_standing_still_is_told_from_stepping_about_most_of_the_time(kit):
    said = {}
    for who in ("still", "shift", "moving") * 3:
        start, rows, _ = kit.play([(8, who)])
        said.setdefault(who, []).extend(s["pred"]["motion"] for t, s in rows if t - start > 3000 and s["pred"]["present"])
        kit.play([(4, "nobody")])
    share = {who: sum(m == "still" for m in v) / len(v) for who, v in said.items()}
    assert share["still"] >= 0.9               # a person standing still is said to be still
    assert share["moving"] <= 0.6              # stepping about is told from it more often than not
    assert share["shift"] >= 0.6               # shifting their weight still reads as standing there


def test_armed_a_person_who_stays_is_an_intrusion_and_one_who_leaves_passed_by(kit):
    kit.brain.on_cmd(cmd("arm", on=True))
    _, rows, events = kit.play([(3, "nobody"), (1.5, "still"), (5, "nobody"), (6, "still"), (4, "nobody")])
    kinds = [e["kind"] for _, e in events if e["kind"] in ("intrusion", "passed_by", "tamper")]
    assert kinds == ["passed_by", "intrusion"]
    assert [e["info"] for _, e in events if e["kind"] == "intrusion"] == [{"zone": 1}]
    kit.brain.on_cmd(cmd("arm", on=False))


def test_armed_pi_b_going_quiet_is_a_tamper_and_coming_back_clears_it():
    kit = Kit(seed=3).teach()
    kit.brain.on_cmd(cmd("arm", on=True))
    kit.play([(4, "nobody")])
    live = dict(kit.feed.next)
    kit.feed.next = {k: (float("inf") if "pi5b" in k else t) for k, t in live.items()}   # Pi B unplugged
    _, rows, events = kit.play([(8, "nobody")])
    assert [(e["kind"], e["info"]) for _, e in events if e["kind"].startswith("tamper")] == [("tamper", {"node": "pi5b"})]
    assert rows[-1][1]["tamper"] == ["pi5b"]
    assert not any(e["kind"] in ("intrusion", "enter") for _, e in events)    # a dead device is never "somebody"
    kit.feed.next = {k: kit.feed.t for k in LINKS}                            # plugged back in
    _, rows, events = kit.play([(8, "nobody")])
    assert [e["kind"] for _, e in events if e["kind"].startswith("tamper")] == ["tamper_cleared"]
    assert rows[-1][1].get("tamper", []) == []


def test_a_three_minute_visit_is_one_enter_and_never_blinks_out(kit):
    kit.play([(4, "nobody")])
    start, rows, events = kit.play([(20, who) for who in ("still", "shift", "moving") * 3])   # 180 s
    assert comings(events) == ["enter"]          # the no-movement alert comes and goes; the person never does
    held = [s["pred"]["present"] for t, s in rows if t - start > 2000]
    assert sum(held) >= 0.99 * len(held)
    _, _, events = kit.play([(5, "nobody")])
    assert comings(events) == ["exit"]


def test_the_hold_only_keeps_somebody_who_was_there_and_never_brings_anybody_in(kit):
    brain = kit.brain
    kit.play([(5, "nobody")])
    assert brain.pred["present"] is False and brain._still_down() is False       # nobody there: nothing to hold
    kit.play([(5, "still")])
    assert brain.pred["present"] is True and brain._still_down() is True         # there, and the lines are down
    window = dict(brain.window, links={k: dict(v, mean=brain.base[k], median=brain.base[k], min=brain.base[k],
                                               max=brain.base[k], std=0.0) for k, v in brain.window["links"].items()})
    assert brain.model.predict(window, hold=True)["present"] is True              # held, whatever the forest says
    assert brain.model.predict(window, hold=False)["present"] is False            # every line on its baseline: nobody
    kit.play([(5, "nobody")])


def test_three_links_are_enough():
    """Pi B as a beacon only, heard by the board and Pi A: two lines across the spot and the desk's Wi-Fi line."""
    keep = ["pi5>unoq:wifi", "pi5b>unoq:ble", "pi5b>pi5:ble"]
    kit = Kit(seed=5)
    kit.brain = Brain(nodes=dict(GATE, links=[link for link in GATE["links"] if link["id"] in keep]))
    send = kit._send
    kit._send = lambda msg: send(msg) if msg.get("link", keep[0]) in keep else None
    kit.teach()
    assert kit.brain.links == tuple(keep) and kit.brain.crossing == ("pi5b>unoq:ble", "pi5b>pi5:ble")
    assert len(kit.brain.model.features) == 3 * 4 + 2 + 1
    for who in ("still", "moving", "shift"):
        start, rows, events = kit.play([(6, who)])
        assert comings(events) == ["enter"] and (when(events, "enter") - start) / 1000 <= 1.5
        assert rows[-1][1]["pred"]["probs"][1] > 0.5 and len(rows[-1][1]["links"]) == 3
        start, _, events = kit.play([(5, "nobody")])
        assert comings(events) == ["exit"] and (when(events, "exit") - start) / 1000 <= 2.0
    _, rows, events = kit.play([(120, "nobody")])
    assert comings(events) == [] and not any(s["pred"]["present"] for _, s in rows)
    assert not any(e["kind"].startswith("object") for _, e in events)
    assert rows[-1][1]["health"]["status"] == "ok" and rows[-1][1]["xray"]["n_links"] == 3
