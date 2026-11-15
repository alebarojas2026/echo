"""The whole brain on the gate layout: three devices, six links, one spot (gate_nodes.json here).

The feed is made up (brain/tests/gatefeed.py), shaped like what the kit gave: about 6 readings
a second on the lines to Pi B (one at 2), a 2 to 5 dB wobble with nobody there and a drop of
about 8 dB with a person on the spot; and the Wi-Fi line from Pi A to Pi B, 25 readings a second, steady
when empty and 18 dB down with a person: the line that decides (the layout's "presence"). It shows the rules hold at those numbers. It is not a
measurement of the real desk.
"""
import json
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
    # pi5b>pi5:ble was unreliable on the kit: the file says it is no classifier link, so it is no feature
    assert brain.model_links == tuple(k for k in LINKS if k != "pi5b>pi5:ble")
    assert brain.crossing == ("pi5b>unoq:ble", "pi5>pi5b:wifi", "pi5>pi5b:ble")
    assert (brain.presence_line, brain.presence_second) == ("pi5>pi5b:wifi", None)   # "second" is read and not used
    assert (brain.presence_on_db, brain.presence_off_db, brain.presence_hold_ms) == (7.0, 4.0, 5000)
    # the presence line is the sensor: it alone can blind it, and only by going silent or stale
    assert list(brain.health.classifier_links) == ["pi5>pi5b:wifi"] and brain.health.judge_level is False
    zone = zone_rule(GATE)
    assert [zone(0.4, 0.3), zone(0.0, 0.0), zone(0.8, 0.6)] == [1, 1, 1]
    assert [zone(0.4, -0.1), zone(0.4, 0.7), zone(-0.1, 0.3), zone(0.9, 0.3)] == [0, 0, 0, 0]   # standing back is not on the spot
    xray = Xray.from_nodes(GATE)
    assert grid_shape(GATE["frame"]) == (10, 14)
    assert (xray.grid.w, xray.grid.h, round(xray.grid.cell_m, 4)) == (10, 14, 0.125)
    assert [round(v, 4) for v in xray.grid.origin_m] == [-0.2, -0.2] and xray.W.shape == (6, 140)
    assert brain.xray.W.shape == (5, 140)
    assert xray.nodes["pi5b"] == (0.4, -0.2)     # a device may sit outside frame.size_m


def test_the_model_has_two_classes_and_probs_is_empty_then_the_spot(kit):
    assert kit.brain.model.classes == [0, 1] and len(kit.brain.model.features) == 5 * 4 + 3 + 1   # and the three crossing lines' medians, and their average
    _, rows, _ = kit.play([(5, "still")])
    pred = rows[-1][1]["pred"]
    assert pred["present"] is True and pred["zone"] == 1 and pred["zone_set"] == [1] and pred["kind"] == "person"
    assert len(pred["probs"]) == 2 and abs(sum(pred["probs"]) - 1) < 0.01 and pred["probs"][1] > 0.5
    assert set(pred["why"]) <= set(kit.brain.crossing) and "pi5>pi5b:wifi" in pred["why"]   # the lines that cross the spot
    _, rows, _ = kit.play([(5, "nobody")])
    pred = rows[-1][1]["pred"]
    assert (pred["present"], pred["zone"], pred["zone_set"], pred["motion"], len(pred["probs"])) == (False, 0, [], None, 2)
    state = rows[-1][1]
    assert [row["id"] for row in state["links"]] == LINKS and state["health"]["status"] == "ok"
    assert state["xray"]["w"] == 10 and state["xray"]["h"] == 14 and state["xray"]["n_links"] == 5
    # the state passes the schema, apart from the length of probs where the schema is still pinned to two zones
    assert [e for e in check.errors(state) if "probs" not in e] == []


def test_stepping_on_is_found_within_a_second_and_a_half_and_released_within_two(kit):
    found, released = [], []
    for i in range(10):
        start, rows, events = kit.play([(6, ("still", "shift", "moving")[i % 3])])
        assert comings(events) == ["enter"], i
        found.append((when(events, "enter") - start) / 1000)
        held = [s["pred"]["present"] for t, s in rows if t - start > 2000]
        assert sum(held) >= 0.95 * len(held)                                      # and held: no exit, hardly a flicker
        start, rows, events = kit.play([(5, "nobody")])
        assert comings(events) == ["exit"], i
        released.append((when(events, "exit") - start) / 1000)
        assert not any(s["pred"]["present"] for t, s in rows if t - start > 2500)
    assert max(found) <= 1.5 and max(released) <= 2.0, (found, released)
    assert statistics.median(found) <= 1.2


def test_ten_minutes_of_an_empty_spot_show_nobody(kit):
    _, rows, events = kit.play([(600, "nobody")])
    assert len(rows) > 5000 and all(s["pred"] is not None for _, s in rows)       # never blind, never unknown
    assert [e["kind"] for _, e in events if e["kind"] not in ("recording", "trained", "cam_off")] == []   # no enter, no object, nothing
    assert sum(s["pred"]["present"] for _, s in rows) <= 2                        # not even a flicker held


def test_standing_still_is_told_from_stepping_about_nine_times_in_ten(kit):
    """Moving and still come from the Wi-Fi line's spread over 2 s (25 readings a second, under 1 dB when
    empty), not from the Bluetooth lines, which wobble 2 to 5 dB by themselves."""
    said = {}
    for who in ("still", "shift", "moving") * 4:
        start, rows, _ = kit.play([(10, who)])
        said.setdefault(who, []).extend(s["pred"]["motion"] for t, s in rows if t - start > 3000 and s["pred"]["present"])
        kit.play([(4, "nobody")])
    share = {who: sum(m == "still" for m in v) / len(v) for who, v in said.items()}
    assert share["still"] >= 0.9, share        # a person standing still is said to be still
    assert share["moving"] <= 0.1, share       # stepping about is said to be moving
    assert share["shift"] >= 0.6, share        # shifting their weight still reads as standing there


def test_where_moving_begins_comes_from_the_file_and_then_from_the_lesson(kit):
    from brain.train import best_split
    assert Brain(nodes=GATE).moving_spread_db == 2.0 and Brain(nodes=GATE).object_spread_db == 1.0     # the defaults
    tuned = Brain(nodes=dict(GATE, presence=dict(GATE["presence"], moving_spread_db=3.5, object_db=4, object_max_db=None,
                                                 object_spread_db=0.6, object_hold_s=2)))
    assert (tuned.moving_spread_db, tuned.object_db, tuned.object_max_db, tuned.object_spread_db, tuned.object_hold_ms) \
        == (3.5, 4.0, float("inf"), 0.6, 2000)
    # the lesson had moving and still windows on the line: its labels put the boundary between them
    split = kit.brain.model.spread_split
    assert kit.brain.model.motion_line == "pi5>pi5b:wifi" and split is not None and 0.8 < split < 3.5, split
    # too few windows of a kind, or kinds that don't come apart: the file's value stands
    assert best_split([0.4] * 30, [3.0] * 5) is None and best_split([1.0, 2.0] * 20, [1.0, 2.0] * 20) is None
    assert best_split([0.4, 0.6] * 15, [2.5, 3.5] * 15) == 1.55
    # a brain with no lesson boundary uses the file's: 2 dB, and still again under 80% of it
    brain = Brain(nodes=GATE)
    brain.window = {"long": {"pi5>pi5b:wifi": {"n": 50, "median": -65.0, "std": 1.9}}}
    assert brain._motion_says() == "still"
    for std, says in ((2.1, "moving"), (1.7, "moving"), (1.5, "still"), (1.9, "still"), (None, "still")):
        brain.window["long"]["pi5>pi5b:wifi"]["std"] = std
        assert brain._motion_says() == says, std


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


def test_the_wifi_line_decides_and_no_bluetooth_line_has_a_say(kit):
    brain = kit.brain
    kit.play([(5, "nobody")])
    assert brain.pred["present"] is False and brain._line_says() is False
    kit.play([(5, "still")])
    assert brain.pred["present"] is True and brain._line_says() is True
    flat = {k: dict(v, mean=brain.base[k], median=brain.base[k], min=brain.base[k], max=brain.base[k], std=0.0)
            for k, v in brain.window["links"].items()}
    down = lambda link, db: dict(flat[link], mean=brain.base[link] - db, median=brain.base[link] - db)   # noqa: E731
    assert brain.model.predict(dict(brain.window, links=flat), present=True)["present"] is True      # the line's word stands
    assert brain.model.predict(brain.window, present=False)["present"] is False
    # on at 7 dB, off under 4 dB: 5 dB keeps somebody who is there and brings nobody in
    wifi, ble, end = "pi5>pi5b:wifi", "pi5b>unoq:ble", brain.window["end"]
    brain.window = dict(brain.window, links={**flat, wifi: down(wifi, 5.0)})
    assert brain._line_says() is True
    brain.window = dict(brain.window, links={**flat, wifi: down(wifi, 3.0)})
    assert brain._line_says() is False
    brain.window = dict(brain.window, links={**flat, wifi: down(wifi, 5.0)})
    assert brain._line_says() is False
    # the Bluetooth line alone never raises presence ...
    silent = dict(flat[wifi], n=0, median=None, mean=None)
    brain.window = dict(brain.window, links={**flat, wifi: silent, ble: down(ble, 9.0)})
    assert brain._line_says() is False
    # ... and does not hold it either: when the Wi-Fi line goes silent with somebody there, its own last
    # word stands for 5 s whatever the Bluetooth line reads (by then the sensor is blind), and then goes
    brain.window = dict(brain.window, links={**flat, wifi: down(wifi, 16.0)})
    assert brain._line_says() is True
    brain.window = dict(brain.window, end=end + 3000, links={**flat, wifi: silent})
    assert brain._line_says() is True
    brain.window = dict(brain.window, end=end + 6000, links={**flat, wifi: silent, ble: down(ble, 9.0)})
    assert brain._line_says() is False
    kit.play([(5, "nobody")])


def bent(kit, bend):
    """The kit's feed with each reading passed through bend(link, seconds since now, dbm) on its way to the brain."""
    send, t0 = kit._send, kit.feed.t

    def through(msg):
        if msg["type"] == "rssi":
            msg = dict(msg, dbm=round(bend(msg["link"], (msg["recv_t"] - t0) / 1000, msg["dbm"])))
        send(msg)
    kit._send = through
    return kit


def test_a_bluetooth_dip_and_a_drifting_desk_line_never_blind_the_sensor_or_make_an_object_or_a_person():
    """What the kit's recordings showed with nobody there: the Bluetooth lines dip 9 to 20 dB by themselves,
    and the 8 cm Wi-Fi line on the desk climbed 9 dB over one run. On a layout with a presence line none
    of that is the sensor's business: no SENSOR BLIND, no object, no advice, nobody."""
    def bend(link, s, dbm):
        if link == "pi5>unoq:wifi":
            return dbm + 9.0 * min(s, 600) / 600              # the desk line drifts 9 dB over ten minutes
        if link.endswith(":ble") and s % 60 < 5:
            return dbm - 12.0                                 # every Bluetooth line dips 12 dB for 5 s, once a minute
        return dbm

    kit = bent(Kit(seed=11).teach(), bend)
    _, rows, events = kit.play([(600, "nobody")])
    kinds = {e["kind"] for _, e in events}
    assert not kinds & {"blind_on", "object_on", "advice", "enter", "intrusion"}, kinds
    assert all(s["health"]["status"] != "blind" and s["health"]["blind"] == [] for _, s in rows)
    assert all(s["pred"] is not None and s["pred"]["present"] is False and s["pred"]["kind"] == "none" for _, s in rows)
    assert all(s["objects"] == [] and s["advice"] is None for _, s in rows)
    assert not any(row["status"] == "blind" for _, s in rows for row in s["links"])
    # and a person is still found afterwards, and let go
    start, _, events = kit.play([(6, "still")])
    assert comings(events) == ["enter"] and (when(events, "enter") - start) / 1000 <= 1.5
    _, _, events = kit.play([(5, "nobody")])
    assert comings(events) == ["exit"]


def test_the_presence_line_going_silent_is_the_one_thing_that_blinds_the_sensor():
    kit = Kit(seed=12).teach()
    kit.play([(5, "nobody")])
    live = kit.feed.next["pi5>pi5b:wifi"]
    kit.feed.next["pi5>pi5b:wifi"] = float("inf")             # Pi B's Wi-Fi reader stops; its Bluetooth lines carry on
    _, rows, events = kit.play([(10, "nobody")])
    assert [e["info"]["link"] for _, e in events if e["kind"] == "blind_on"] == ["pi5>pi5b:wifi"]
    assert rows[-1][1]["health"] == {"status": "blind", "blind": ["pi5>pi5b:wifi"], "reason": "rate"}
    assert rows[-1][1]["pred"] is None                         # unknown, never "nobody"
    assert "enter" not in comings(events)
    kit.feed.next["pi5>pi5b:wifi"] = kit.feed.t                # and it is back
    _, rows, events = kit.play([(10, "nobody")])
    assert [e["kind"] for _, e in events if e["kind"].startswith("blind")] == ["blind_off"]
    assert rows[-1][1]["health"]["status"] == "ok" and rows[-1][1]["pred"]["present"] is False
    del live


def test_three_links_are_enough():
    """gate-3: only the three lines that cross the spot."""
    keep = ["pi5b>unoq:ble", "pi5>pi5b:wifi", "pi5b>pi5:ble"]
    kit = Kit(seed=5)
    kit.brain = Brain(nodes=dict(GATE, links=[link for link in GATE["links"] if link["id"] in keep]))
    send = kit._send
    kit._send = lambda msg: send(msg) if msg.get("link", keep[0]) in keep else None
    kit.teach()
    assert kit.brain.links == tuple(keep) and kit.brain.crossing == ("pi5b>unoq:ble", "pi5>pi5b:wifi")
    assert len(kit.brain.model.features) == 2 * 4 + 2 + 1
    for who in ("still", "moving", "shift"):
        start, rows, events = kit.play([(6, who)])
        assert comings(events) == ["enter"] and (when(events, "enter") - start) / 1000 <= 1.5
        assert rows[-1][1]["pred"]["probs"][1] > 0.5 and len(rows[-1][1]["links"]) == 3
        start, _, events = kit.play([(5, "nobody")])
        assert comings(events) == ["exit"] and (when(events, "exit") - start) / 1000 <= 2.0
    _, rows, events = kit.play([(120, "nobody")])
    assert comings(events) == [] and not any(s["pred"]["present"] for _, s in rows)
    assert not any(e["kind"].startswith("object") for _, e in events)
    assert rows[-1][1]["health"]["status"] == "ok" and rows[-1][1]["xray"]["n_links"] == 2


# What the kit's acceptance run showed (issue #95): the one good line falls 3 to 12 dB with a person,
# typically 7; its empty level drifted 5 dB in five minutes; a walk straight through is a 5 to 7 dB dip
# of a second or two.
WEAK = {"pi5>pi5b:wifi": 15.0, "pi5b>unoq:ble": 4.5, "pi5>pi5b:ble": 4.0, "pi5b>pi5:ble": 2.0}   # the weakest person seen


def drifting_kit(seed=7, **feed):
    kit = Kit(seed)
    kit.feed = Feed(T0_MS, seed, 1.0, drift_db_per_min=1.0, **feed)
    return kit.teach()


def test_the_empty_level_follows_a_drift_of_five_db_in_five_minutes():
    line = "pi5>pi5b:wifi"
    kit = bent(Kit(7).teach(), lambda link, s, dbm: dbm - min(s, 300) / 60 if link == line else dbm)   # 1 dB a minute
    start = dict(kit.brain.base)
    _, rows, events = kit.play([(300, "nobody")])
    assert comings(events) == [] and not any(s["pred"]["present"] for _, s in rows)     # the drift is never "somebody"
    assert not any(e["kind"].startswith("object") or e["kind"] == "advice" for _, e in events)
    assert 3.5 <= start[line] - kit.brain.base[line] <= 6.5                             # 5 dB down, followed
    assert all(kit.brain.base[k] == start[k] for k in start if k != line)               # only the presence line follows
    # after the drift a person is still found, and still released
    start_ms, _, events = kit.play([(6, "still")])
    assert comings(events) == ["enter"] and (when(events, "enter") - start_ms) / 1000 <= 1.5
    start_ms, _, events = kit.play([(5, "nobody")])
    assert comings(events) == ["exit"] and (when(events, "exit") - start_ms) / 1000 <= 2.0


def test_a_bluetooth_line_dipping_is_never_a_check_in_and_never_moves_the_empty_level():
    """The kit's Bluetooth lines dip 12 to 20 dB with nobody near them. On a layout with a presence line the
    lean-aside check-in and the drift follow read that line alone, so the dips do nothing."""
    def dips(link, s, dbm):
        if link.endswith(":ble") and s % 20 < 4:
            return dbm - (12.0 if int(s // 20) % 2 else 20.0)     # 4 s down, every 20 s, 12 or 20 dB
        return dbm

    kit = bent(Kit(seed=14).teach(), dips)
    assert kit.brain.sense == ("pi5>pi5b:wifi",)
    start = dict(kit.brain.base)
    _, rows, events = kit.play([(180, "nobody")])
    kinds = {e["kind"] for _, e in events}
    assert not kinds & {"checkin", "enter", "blind_on", "object_on", "advice"}, kinds
    assert all(s["checkin"] is None and s["pred"]["present"] is False for _, s in rows)
    ble = [k for k in start if k.endswith(":ble")]
    assert all(kit.brain.base[k] == start[k] for k in ble)                       # no Bluetooth level moved
    assert abs(kit.brain.base["pi5>pi5b:wifi"] - start["pi5>pi5b:wifi"]) < 0.5   # and the line's own stayed put
    # somebody standing still while the Bluetooth lines come back up from a dip: the alert stays, no check-in
    _, rows, events = kit.play([(40, "still")])
    assert alerts(events) == ["alert_on"] and rows[-1][1]["alert"]["state"] == "check_on"
    # and a real lean still clears it
    _, rows, events = kit.play([(1.0, "lean"), (4, "still")])
    assert alerts(events) == ["checkin", "alert_off"]


def test_with_a_fixed_baseline_a_drift_of_the_bluetooth_lines_is_not_followed_and_still_blinds_nothing():
    """drift_follow_s 0 is the fixed 20 s baseline of the contract. The Bluetooth lines then end up 8 dB off
    it, which used to end blind or as somebody who is not there; with a presence line their level has no say."""
    from brain import settings as S
    kit = Kit(7)
    kit.brain = Brain(nodes=GATE, settings=S.DEFAULT.with_(drift_follow_s=0))
    kit.feed = Feed(T0_MS, 7, 1.0, drift_db_per_min=1.6)
    kit.teach()
    start = dict(kit.brain.base)
    _, rows, events = kit.play([(300, "nobody")])
    assert kit.brain.base == start                                                      # not followed
    assert comings(events) == [] and all(s["pred"] is not None and not s["pred"]["present"] for _, s in rows)
    assert all(s["health"]["status"] != "blind" for _, s in rows)


def test_a_person_standing_still_for_three_minutes_is_never_taken_for_the_empty_spot():
    kit = drifting_kit()
    kit.play([(20, "nobody")])
    kit.play([(2, "still")])
    held = dict(kit.brain.base)
    _, rows, events = kit.play([(180, "still")])
    assert comings(events) == [] and all(s["pred"]["present"] for _, s in rows)
    assert kit.brain.base == held                                   # frozen from the moment they stepped in
    _, _, events = kit.play([(6, "nobody")])
    assert comings(events) == ["exit"]


def test_the_weakest_person_is_found_and_kept():
    kit = drifting_kit(drop=WEAK)
    # taught on this person: the lesson's labels are what set where "present" begins
    found = 0
    for _ in range(10):
        _, rows, events = kit.play([(6, "still")])
        found += comings(events)[:1] == ["enter"] and comings(events).count("exit") == 0
        kit.play([(6, "nobody")])
    assert found == 10, found


def test_a_walk_straight_through_is_passed_by_and_never_an_intrusion():
    kit = Kit(seed=11).teach()
    kit.brain.on_cmd(cmd("arm", on=True))
    kit.play([(5, "nobody")])
    seen = []
    for seconds in (1.0, 1.5, 2.0, 1.2, 1.8):
        _, _, events = kit.play([(seconds, "moving"), (8, "nobody")])
        seen += [e["kind"] for _, e in events if e["kind"] in ("intrusion", "passed_by")]
    assert "intrusion" not in seen and seen.count("passed_by") >= 3, seen
    _, _, events = kit.play([(6, "still"), (4, "nobody")])          # somebody who stops is an intrusion
    assert [e["kind"] for _, e in events if e["kind"] in ("intrusion", "passed_by")] == ["intrusion"]


def cold_kit(seed):
    """A brain started cold on the gate: a baseline, and no lesson, no camera, no model."""
    kit = Kit(seed)
    kit.brain.on_cmd(cmd("baseline"))
    kit.play([(26, "nobody")])
    assert [e["kind"] for _, e in kit.events if e["kind"] == "baseline_done"] == ["baseline_done"]
    assert kit.brain.model is None
    return kit


def test_with_no_model_and_no_lesson_the_presence_line_alone_gives_the_whole_decision():
    """The camera is not used: no lesson is ever run. On a layout with a presence line the brain still
    publishes a full decision, and everything that follows from it works (made-up feed, not a measurement)."""
    kit = cold_kit(seed=21)
    first = len(kit.rows)
    kit.play([(5, "nobody")])
    assert kit.rows[-1][1]["pred"] == {"present": False, "kind": "none", "zone": 0, "zone_set": [], "probs": [1.0, 0.0],
                                        "motion": None, "still_s": 0.0, "why": []}
    start, rows, events = kit.play([(10, "still")])                       # step on, 10 s
    assert comings(events) == ["enter"] and (when(events, "enter") - start) / 1000 <= 1.5
    here = [s["pred"] for t, s in rows if t - start > 2000]
    assert all(p["present"] and p["kind"] == "person" and p["zone"] == 1 and p["zone_set"] == [1]
               and p["probs"] == [0.0, 1.0] and p["why"] == ["pi5>pi5b:wifi"] for p in here)
    assert sum(p["motion"] == "still" for p in here) >= 0.9 * len(here)
    start, rows, _ = kit.play([(8, "moving")])                            # stepping about on the spot
    moving = [s["pred"]["motion"] for t, s in rows if t - start > 3000]
    assert moving.count("moving") >= 0.6 * len(moving)
    start, _, events = kit.play([(5, "nobody")])                          # off
    assert comings(events) == ["exit"] and (when(events, "exit") - start) / 1000 <= 2.0
    _, rows, events = kit.play([(15, "still")])                           # stand still 15 s: the alert at 10 s
    assert alerts(events) == ["alert_on"] and rows[-1][1]["alert"]["state"] == "check_on"
    _, _, events = kit.play([(1.0, "lean"), (4, "still")])                # lean aside: the check-in
    assert alerts(events) == ["checkin", "alert_off"]
    kit.play([(5, "nobody")])
    kit.brain.on_cmd(cmd("arm", on=True))                                 # armed: a walk through, then somebody who stays
    _, _, events = kit.play([(3, "nobody"), (1.5, "moving"), (6, "nobody"), (6, "still"), (4, "nobody")])
    assert [e["kind"] for _, e in events if e["kind"] in ("intrusion", "passed_by")] == ["passed_by", "intrusion"]
    kit.brain.on_cmd(cmd("arm", on=False))
    _, rows, events = kit.play([(10, "thing")])                           # a thing left in the line
    assert rows[-1][1]["pred"]["kind"] == "object" and rows[-1][1]["pred"]["present"] is False
    assert rows[-1][1]["advice"]["to_spot"] is None and "enter" not in comings(events)
    kit.play([(8, "nobody")])
    # the model says honestly that no lesson has been run, and every state is the contract's
    states = [s for _, s in kit.rows[first:]]
    assert all(s["model"]["trained"] is False and s["pred"] is not None for s in states)
    bad = [err for s in states for err in check.errors(json.loads(json.dumps(s)), layout=GATE)]
    assert not bad, bad[:5]


def test_a_pause_of_the_presence_line_never_blanks_the_decision():
    """The line's readings come over the hotspot and can pause for a second. Its last word stands meanwhile:
    1.5 s without readings keeps somebody there, keeps nobody as nobody, and pred is never null."""
    line = "pi5>pi5b:wifi"

    def pause(kit, who, seconds=1.5):
        kit.feed.next[line] = float("inf")
        _, rows, events = kit.play([(seconds, who)])
        kit.feed.next[line] = kit.feed.t
        _, after, more = kit.play([(3, who)])
        return rows + after, events + more

    kit = cold_kit(seed=24)
    kit.play([(5, "nobody")])
    rows, events = pause(kit, "nobody")                                   # empty spot, the line pauses
    assert all(s["pred"] is not None and s["pred"]["present"] is False for _, s in rows)
    assert all(s["health"]["status"] != "blind" for _, s in rows) and comings(events) == []
    kit.play([(6, "still")])
    rows, events = pause(kit, "still")                                    # somebody standing there, the line pauses
    assert all(s["pred"] is not None and s["pred"]["present"] and s["pred"]["kind"] == "person" for _, s in rows)
    assert comings(events) == [] and not any(e["kind"].startswith("blind") for _, e in events)
    # a line that stays silent is another matter: the sensor goes blind and the decision is hidden
    kit.feed.next[line] = float("inf")
    _, rows, events = kit.play([(10, "still")])
    assert rows[-1][1]["health"]["status"] == "blind" and rows[-1][1]["pred"] is None


def test_with_no_model_ten_empty_minutes_give_nothing():
    kit = cold_kit(seed=22)
    kit.brain.on_cmd(cmd("arm", on=True))
    _, rows, events = kit.play([(600, "nobody")])
    kinds = {e["kind"] for _, e in events} - {"armed"}
    assert not kinds & {"enter", "exit", "intrusion", "passed_by", "alert_on", "checkin", "object_on", "advice", "blind_on"}, kinds
    assert all(s["pred"] is not None and s["pred"]["present"] is False and s["pred"]["kind"] == "none" for _, s in rows)


def test_a_layout_with_no_presence_line_still_waits_for_a_model():
    plain = dict(GATE)
    plain.pop("presence")
    kit = Kit(seed=23)
    kit.brain = Brain(nodes=plain)
    kit.brain.on_cmd(cmd("baseline"))
    _, rows, _ = kit.play([(26, "nobody"), (6, "still")])
    assert kit.brain.model is None and rows[-1][1]["pred"] is None and rows[-1][1]["model"]["trained"] is False


def alerts(events):
    return [e["kind"] for _, e in events if e["kind"] in ("alert_on", "alert_off", "checkin")]


def test_leaning_aside_is_the_check_in_and_leaving_ends_the_alert_without_one():
    kit = Kit(seed=13).teach()
    kit.play([(4, "nobody")])
    done = 0
    for lean_s in (0.8, 1.0, 1.3, 1.6, 1.0, 0.8, 1.3, 1.0, 1.6, 1.0):
        _, rows, events = kit.play([(14, "still")])                   # the limit is 10 s
        assert alerts(events) == ["alert_on"] and rows[-1][1]["alert"]["state"] == "check_on"
        _, rows, events = kit.play([(lean_s, "lean"), (4, "still")])
        done += alerts(events) == ["checkin", "alert_off"] and rows[-1][1]["checkin"] is not None
        kit.brain.on_cmd(cmd("reset_alert"))
        kit.play([(5, "nobody")])
        kit.brain.pop_events()
    assert done >= 8, done
    # standing there, still or shifting, is never taken for a check-in
    _, _, events = kit.play([(14, "still"), (60, "shift"), (60, "still")])
    assert alerts(events) == ["alert_on"]
    # and walking away ends the alert with no check-in said
    _, rows, events = kit.play([(8, "nobody")])
    assert alerts(events) == ["alert_off"] and rows[-1][1]["alert"]["state"] == "none"


def things(events):
    return [e["kind"] for _, e in events if e["kind"] in ("advice", "advice_result", "enter", "exit", "intrusion", "passed_by",
                                                         "alert_on", "blind_on")]


def test_a_thing_left_in_the_wifi_line_is_an_object_never_a_person_and_its_removal_shows_the_gain():
    kit = Kit(seed=17).teach()
    kit.brain.on_cmd(cmd("arm", on=True))                # armed all through: a thing is never an intrusion
    kit.play([(6, "nobody")])
    kit.brain.pop_events()
    start, rows, events = kit.play([(30, "thing")])       # left for 30 s
    assert things(events) == ["advice"], things(events)
    assert (when(events, "advice") - start) / 1000 <= 8
    assert not any(s["pred"] is None or s["pred"]["present"] for _, s in rows)       # never somebody, never unknown
    late = [s for t, s in rows if t - start > 8000]
    assert all(s["pred"]["kind"] == "object" and s["pred"]["zone"] == 0 and s["pred"]["motion"] is None for s in late)
    assert all(s["alert"]["state"] == "none" and s["health"]["status"] != "blind" for s in late)
    advice = late[-1]["advice"]
    assert advice["link"] == "pi5>pi5b:wifi" and advice["cause"] == "obstruction" and advice["why"] == ["pi5>pi5b:wifi"]
    assert (advice["to_spot"], advice["move_m"], advice["dist_change_m"], advice["after_dbm"]) == (None, [0, 0], 0, None)
    assert "router" not in advice["text"].lower() and "Pi A to Pi B" in advice["text"]   # nobody is told to move the router
    assert advice["xy_m"] == [0.38, 0.3] and len({s["advice"]["id"] for s in late}) == 1   # the middle of the line; one advice
    assert -53.5 <= advice["before_dbm"] <= -50.5                                    # 5 dB under the empty level of -47
    assert any(s["objects"] for s in late)                                           # and the x-ray lists it
    # the state passes the schema, apart from what the contract change for one spot brings: the length of probs,
    # a null to_spot, and near judged on this layout's own devices
    assert [e for e in check.errors(late[-1]) if not any(k in e for k in ("probs", "to_spot", ".near"))] == []
    held = kit.brain.base["pi5>pi5b:wifi"]
    assert abs(held - -47) <= 1.0                         # the empty level did not follow the thing down

    start, rows, events = kit.play([(20, "nobody")])      # taken away
    assert things(events) == ["advice_result"], things(events)
    result = next(e for _, e in events if e["kind"] == "advice_result")
    assert 5 <= (when(events, "advice_result") - start) / 1000 <= 9      # 3 s of readings, starting 2 s after it went
    assert result["info"]["link"] == "pi5>pi5b:wifi"
    gain = result["info"]["after_dbm"] - result["info"]["before_dbm"]
    assert 4.0 <= gain <= 6.0, gain                       # the 5 dB the thing took, through the fields that were there
    shown = [s["advice"] for _, s in rows if s["advice"] and s["advice"]["after_dbm"] is not None]
    assert shown and shown[0]["after_dbm"] == result["info"]["after_dbm"] and shown[0]["to_spot"] is None
    assert rows[-1][1]["advice"] is None and rows[-1][1]["pred"]["kind"] == "none"   # shown 10 s, then gone
    assert not any(s["pred"]["present"] for _, s in rows)
    kit.brain.on_cmd(cmd("arm", on=False))


def test_a_person_on_the_spot_is_never_a_thing_however_still_and_ends_one_that_was_there():
    kit = Kit(seed=19).teach()
    kit.play([(5, "nobody")])
    _, rows, events = kit.play([(120, "still")])          # two minutes without moving: 18 dB down, as steady as a thing
    assert all(s["pred"]["present"] and s["pred"]["kind"] == "person" for t, s in rows[20:])
    assert not any(s["advice"] for _, s in rows) and "advice" not in things(events)
    kit.brain.on_cmd(cmd("reset_alert"))
    kit.play([(6, "nobody")])
    kit.brain.pop_events()
    # the weakest person seen (15 dB) is one too
    weak = Kit(seed=23)
    weak.feed = Feed(T0_MS, 23, 1.2, drop=WEAK)
    weak.teach().play([(5, "nobody")])
    _, rows, _ = weak.play([(40, "still")])
    assert all(s["pred"]["kind"] == "person" for _, s in rows[20:]) and not any(s["advice"] for _, s in rows)
    # somebody steps in front of a thing: they are found, and the advice goes at once
    kit.play([(15, "thing")])
    assert kit.brain.advice is not None and kit.brain.pred["kind"] == "object"
    start, rows, events = kit.play([(8, "still")])
    assert "enter" in things(events) and (when(events, "enter") - start) / 1000 <= 2.5
    assert rows[-1][1]["pred"]["kind"] == "person" and rows[-1][1]["advice"] is None
    assert "advice_result" not in things(events)          # nothing was taken away, so no gain is claimed


def test_ten_minutes_empty_show_no_thing_and_a_reset_clears_the_advice_while_the_thing_stays(kit):
    kit.play([(8, "nobody")])
    kit.brain.pop_events()
    _, rows, events = kit.play([(600, "nobody")])
    assert not any(s["advice"] or s["objects"] or s["pred"]["kind"] != "none" for _, s in rows)
    assert things(events) == []
    kit.play([(15, "thing")])
    assert kit.brain.advice is not None
    kit.brain.on_cmd(cmd("reset"))
    _, rows, events = kit.play([(10, "thing")])
    assert not any(s["advice"] for _, s in rows) and "advice" not in things(events)   # dismissed while that thing stays
    assert rows[-1][1]["pred"]["kind"] == "object"
    kit.play([(12, "nobody")])
    kit.brain.pop_events()


def test_an_old_classifier_false_on_the_presence_line_does_not_switch_it_off():
    links = [dict(link, classifier=False) if link["id"] == "pi5>pi5b:wifi" else link for link in GATE["links"]]
    brain = Brain(nodes=dict(GATE, links=links))
    assert brain.presence_line == "pi5>pi5b:wifi" and "pi5>pi5b:wifi" in brain.model_links
    assert "pi5>pi5b:wifi" in brain.crossing and "pi5b>pi5:ble" not in brain.model_links   # the other flag still counts


def test_the_wifi_line_reaches_the_brain_at_twenty_readings_a_second_or_more(tmp_path):
    """Pi B's reader -> the bus -> the brain, with nothing in between thinning the presence line: the reader
    polls 25 times a second and sends every fresh reading, the bus stamps and forwards every one, and the
    brain keeps and counts every one."""
    from bus.core import Bus
    from radio import wifi_rssi

    brain = Brain(nodes=GATE)
    line, now = brain.presence_line, [T0_MS / 1000]
    bus = Bus(tmp_path, send=lambda data: brain.on_message(json.loads(data)), clock=lambda: int(now[0] * 1000))
    saved = (wifi_rssi.LINK_ID, wifi_rssi.TX, wifi_rssi.RX, wifi_rssi.KIND)
    wifi_rssi.LINK_ID, wifi_rssi.TX, wifi_rssi.RX, wifi_rssi.KIND = line, "pi5", "pi5b", "wifi"
    frames, seq, seen = [0], [0], []
    try:
        def read(iface, bssid):          # a frame from the hotspot since the last poll (the 50 a second ping)
            frames[0] += 1
            return -47 - frames[0] % 2, frames[0]

        def send(dbm):
            bus.handle(wifi_rssi._make_message(dbm, seq[0]), ("192.168.77.1", 40001))
            seq[0] += 1

        def tick():
            if seq[0] % 25 == 0:
                seen.append(next((row["rate_hz"] for row in brain.state()["links"] if row["id"] == line), 0.0))

        reader = wifi_rssi.Reader("wlan0", "", read=read, say=lambda text: None, link=lambda iface: "")
        spent = wifi_rssi.poll_loop(reader, send, 25.0, seconds=20, tick=tick, clock=lambda: now[0],
                                    sleep=lambda s: now.__setitem__(0, now[0] + s))
    finally:
        wifi_rssi.LINK_ID, wifi_rssi.TX, wifi_rssi.RX, wifi_rssi.KIND = saved
    assert 19.9 <= spent <= 20.1 and seq[0] >= 20 * 24                     # the reader sent 25 a second
    last_10_s = [t for t, _ in brain._recent[line]]
    assert len(last_10_s) >= 10 * 20, len(last_10_s)                      # ... and the brain has them: 20 a second or more
    assert min(seen[3:]) >= 20.0, seen                                    # as the screen's own row for the line says
    window = brain.windower.push({"type": "rssi", "recv_t": int(now[0] * 1000) + 5000, "link": line, "dbm": -47}) \
        if brain.windower else None
    assert window is None                                                 # no baseline yet: nothing was windowed
    assert bus.link_counts[line] == seq[0] and bus.bad == 0               # the bus dropped none
