import json

import pytest

from contracts.check import errors
from sim import fake, state
from sim.wire import encoder

STATE_KEYS = {"type", "t", "cam", "router", "links", "health", "pred", "objects", "xray", "alert", "checkin",
              "advice", "narration", "teacher", "model", "board"}
IDLE = {"state": "none", "zone": None, "still_s": 0, "limit_s": None}
# The one known gap between what the fake brain sends and the schema on main: the schema wants numbers
# once trained is true, and the fake brain measures nothing, so it sends null (contract issue #184).
# Nothing else may fail.
UNMEASURED = {"$.model.train_s: None is not of type 'number'", "$.model.ms_per_decision: None is not of type 'number'"}


def run(name):
    msgs = list(state.run(fake.load_path(name)))
    return [m for m in msgs if m["type"] == "state"], [m for m in msgs if m["type"] == "event"]


def at(states, t):
    return min(states, key=lambda s: abs(s["t"] - t))


def kinds(events):
    return [e["kind"] for e in events]


@pytest.mark.parametrize("name", sorted(p.stem for p in fake.PATHS_DIR.glob("*.json")))
def test_every_message_passes_the_contract_checker(name):
    encode = encoder(1763149500000)
    for m in state.run(fake.load_path(name)):
        assert set(errors(json.loads(encode(m)))) <= UNMEASURED, (name, m["t"])


def test_starts_with_no_readings_no_baseline_and_no_model():
    states, events = run("zone_tour")
    first = states[0]
    assert set(first) == STATE_KEYS and len(states) == 32 * 10
    assert (first["links"], first["xray"], first["pred"], first["objects"]) == ([], None, None, [])
    assert (first["advice"], first["checkin"], first["narration"], first["alert"]) == (None, None, None, IDLE)
    assert first["model"] == {"trained": False, "ver": None, "train_s": None, "ms_per_decision": None,
                              "windows": 0, "train_sessions": [], "training": None}
    assert first["board"] == {"cpu_temp_c": None, "cpu_mhz": None, "cpu_pct": None}
    early = at(states, 0.5)   # readings, but no baseline yet
    assert len(early["links"]) == 6 and early["xray"] is None and early["pred"] is None
    assert {(l["base_dbm"], l["drop_db"], l["expected_hz"], l["status"]) for l in early["links"]} == {(None, None, None, "ok")}
    assert isinstance(early["links"][0]["dbm"], float)
    assert [(e["t"], e["kind"]) for e in events[:3]] == [(1.0, "baseline_done"), (2.0, "trained"), (2.0, "enter")]


def test_after_baseline_and_training():
    states, _ = run("zone_tour")
    based = at(states, 1.5)
    assert len(based["xray"]["moving_db"]) == len(based["xray"]["static_db"]) == 100 and based["pred"] is None
    assert all(isinstance(l["base_dbm"], float) and l["expected_hz"] == 15 for l in based["links"])
    s = at(states, 4)
    assert s["model"] == {"trained": True, "ver": "sim", "train_s": None, "ms_per_decision": None,
                          "windows": 0, "train_sessions": [], "training": None}
    assert set(s["links"][0]) == {"id", "dbm", "base_dbm", "drop_db", "rate_hz", "expected_hz", "status", "why"}
    line = json.loads(encoder(1763149500000)(s))
    assert (line["v"], line["src"], line["t"]) == (2, "sim", 1763149504000)


def test_zone_tour_predictions_events_and_narration():
    states, events = run("zone_tour")
    assert [at(states, t)["pred"]["zone"] for t in (4, 11, 18, 25)] == [3, 4, 2, 1]
    s = at(states, 4)
    assert s["pred"]["kind"] == "person" and s["pred"]["motion"] == "still" and s["pred"]["still_s"] > 2
    assert s["pred"]["why"] == ["west>pi5:ble"] and abs(sum(s["pred"]["probs"]) - 1) < 1e-9
    gone = at(states, 30)["pred"]
    assert (gone["kind"], gone["present"], gone["zone"], gone["zone_set"], gone["motion"]) == ("none", False, 0, [], None)
    assert kinds(events)[2:] == ["enter", "zone_change", "zone_change", "zone_change", "exit"]
    told = at(states, 10)["narration"]
    assert (told["text"], told["source"], told["event_id"]) == ("Someone moved to zone 4.", "template", events[3]["id"])
    assert all(len(text.split()) <= 16 for text in state.SENTENCES.values())


def test_alert_counts_then_fires_and_a_wave_clears_it():
    states, events = run("wave_checkin")
    assert at(states, 6)["alert"]["state"] == "counting" and at(states, 6)["alert"]["limit_s"] == 10
    assert at(states, 13)["alert"]["state"] == "check_on" and at(states, 13)["alert"]["zone"] == 4
    assert at(states, 16)["alert"]["state"] == "counting" and at(states, 16)["checkin"]["link"] == "pi5>unoq:wifi"
    assert at(states, 24.5)["alert"] == IDLE
    assert kinds(events)[2:6] == ["enter", "alert_on", "checkin", "alert_off"]


def test_dropped_link_goes_blind_and_recovers():
    states, events = run("dropped_link")
    assert at(states, 10.5)["health"]["status"] == "ok"  # the 2 s rate has not fallen far enough yet
    assert at(states, 12.5)["health"]["status"] == "degraded" and at(states, 12.5)["pred"]
    blind = at(states, 15)
    assert blind["health"]["status"] == "blind" and blind["pred"] is None and blind["xray"]["n_links"] == 4
    assert at(states, 28)["health"]["status"] == "ok" and at(states, 28)["pred"]["zone"] == 1
    assert kinds(events).count("blind_on") == 2 and kinds(events).count("blind_off") == 2
    assert kinds(events).count("enter") == 1 and "exit" not in kinds(events)  # going blind is not leaving


def test_camera_unplug_keeps_predicting():
    states, events = run("camera_unplug")
    assert at(states, 20)["cam"] == "off" and at(states, 20)["teacher"] is None and at(states, 20)["pred"]["zone"] == 2
    assert "cam_off" in kinds(events)


def test_tray_gets_advice_and_the_router_move_gets_a_result():
    states, events = run("router_move")
    tray = at(states, 40)
    assert tray["pred"]["kind"] == "object" and tray["objects"][0]["near"] == "pi5"
    grid = tray["xray"]["static_db"]
    assert {(i % 10, i // 10) for i in range(100) if grid[i] == max(grid)} == {(4, 1), (5, 1)}  # T1 is between two cells
    advice = tray["advice"]
    assert at(states, 29)["advice"] is None and at(states, 31)["advice"]  # 5 s after the tray lands at 25 s
    assert (advice["to_spot"], advice["move_m"], advice["dist_change_m"], advice["link"]) == ("S-W30", [-0.3, 0.0], 0.02, "pi5>unoq:wifi")
    assert advice["text"].endswith("Move the router 30 cm west.") and advice["near"] == "pi5"
    assert -58 < advice["before_dbm"] < -54 and advice["after_dbm"] is None and "pi5>unoq:wifi" in advice["why"]
    moved = at(states, 48)   # router moved at 45 s
    assert moved["router"] == "S-W30" and moved["pred"] is None and moved["advice"]["after_dbm"] is None
    done = at(states, 52)["advice"]
    assert abs(done["before_dbm"] - advice["before_dbm"]) < 1.5   # frozen at the move
    assert done["after_dbm"] - done["before_dbm"] > 4   # the move cleared the link
    assert at(states, 70)["advice"] is None             # router home, tray gone
    assert kinds(events)[2:] == ["object_on", "advice", "router_moved", "advice_result", "object_off", "router_home"]
    result = next(e for e in events if e["kind"] == "advice_result")["info"]
    assert (result["before_dbm"], result["after_dbm"]) == (done["before_dbm"], done["after_dbm"])


def test_demo_walks_the_whole_story_in_order():
    _, events = run("demo")
    story = ["baseline_done", "trained", "enter", "checkin", "object_on", "advice", "router_moved", "advice_result",
             "router_home", "cam_off", "alert_on", "checkin", "alert_off", "blind_on", "blind_off", "exit"]
    seen = iter(kinds(events))
    assert all(kind in seen for kind in story), kinds(events)   # each one appears, in this order
    assert len({e["id"] for e in events}) == len(events)


def test_reset_alert_and_reset_commands():
    brain = state.Brain(fake.load_path("wave_checkin"))
    states = []
    for m in state.run(brain.path, brain=brain):
        if m["type"] == "state":
            states.append(m)
            if m["t"] == 12.0:
                brain.command({"cmd": "reset_alert"})
            if m["t"] == 18.0:
                brain.command({"cmd": "reset"})
    assert at(states, 11.9)["alert"]["state"] == "check_on" and at(states, 12.5)["alert"]["state"] == "counting"
    before, after = at(states, 17.9), at(states, 18.1)
    assert before["checkin"] and before["narration"] and before["pred"]["still_s"] > 10
    assert (after["checkin"], after["advice"]) == (None, None)
    assert after["narration"]["text"].startswith("Someone visited the Bathroom zone.")   # the recap, not the last sentence
    assert after["pred"]["still_s"] < 0.5 and after["alert"]["still_s"] < 0.5


def test_object_far_from_every_node_has_no_near_but_still_gets_advice():
    middle = {"name": "m", "duration_s": 12, "person": None, "objects": [{"x": 1.0, "y": 1.0, "drop_db": 8, "t_on": 2}]}
    msgs = list(state.run(middle))
    states, events = [m for m in msgs if m["type"] == "state"], [m for m in msgs if m["type"] == "event"]
    encode = encoder(1763149500000)
    assert all(set(errors(json.loads(encode(m)))) <= UNMEASURED for m in msgs)
    s = at(states, 10)
    assert s["objects"][0]["near"] is None and s["advice"]["near"] is None
    assert s["advice"]["text"] == ("On the router's link, an obstruction is blocking its link to the receiver. "
                                   "Move the router 30 cm west.")
    assert isinstance(s["advice"]["before_dbm"], float)
    assert [(e["kind"], e["info"].get("node", "-")) for e in events[2:]] == [("object_on", "-"), ("advice", "-")]   # no node to name
    assert at(states, 5)["narration"]["text"] == "Something new is sitting in the room."
    assert state.near(fake.NODES, (1.0, 0.2)) == "pi5" and state.near(fake.NODES, (1.0, 0.6)) is None


# ---- the three section 6 rules the fake brain follows since the contract update ----

def states_of(path):
    msgs = list(state.run(path))
    return [m for m in msgs if m["type"] == "state"], [m for m in msgs if m["type"] == "event"]


def test_one_moving_flicker_does_not_reset_the_still_timer():
    states, events = run("still_flicker")
    assert at(states, 7.1)["pred"]["motion"] == "moving"            # the wrong decision is shown as it is
    assert at(states, 7.6)["pred"]["still_s"] > at(states, 6.9)["pred"]["still_s"] > 4   # and the timer runs on
    fired = next(e["t"] for e in events if e["kind"] == "alert_on")
    plain = dict(fake.load_path("still_flicker"), flickers=[])
    assert fired == next(e["t"] for e in states_of(plain)[1] if e["kind"] == "alert_on")
    assert 11.0 <= fired <= 12.0                                    # 10 s after standing still begins


def test_five_moving_decisions_in_a_row_do_reset_it():
    long = dict(fake.load_path("still_flicker"), flickers=[{"t_on": 7.0, "t_off": 7.6}])
    states, events = states_of(long)
    assert at(states, 7.35)["pred"]["still_s"] > 4 and at(states, 7.7)["pred"]["still_s"] < 0.3
    assert not [e for e in events if e["kind"] == "alert_on"]       # only 8.4 s left before they walk out


def test_another_zone_resets_the_still_timer_once_it_holds_the_majority():
    hop = {"name": "h", "duration_s": 12, "person": [{"t": 0, "x": 0.9, "y": 0.5}, {"t": 6, "x": 0.9, "y": 0.5},
                                                      {"t": 6.2, "x": 1.1, "y": 0.5}]}   # a short step, zone 3 to 4
    states, _ = states_of(hop)
    assert at(states, 6.4)["pred"]["zone"] == 4 and at(states, 6.4)["pred"]["still_s"] > 3   # not yet the majority
    assert at(states, 6.9)["pred"]["still_s"] < 0.5
    assert at(states, 6.4)["alert"] == IDLE and at(states, 8)["alert"]["zone"] == 4


def jump(db, **extra):
    return {"name": "j", "duration_s": 20, "person": None,
            "jumps": [{"link": "east>unoq:ble", "db": db, "t_on": 5, "t_off": 12, **extra}]}


def test_jump_rule_blinds_a_link_that_sits_off_base():
    states, events = states_of(jump(+9))   # above base: never an object
    assert at(states, 7)["health"]["status"] == "ok"
    blind = at(states, 10)
    assert blind["health"] == {"status": "blind", "blind": ["east>unoq:ble"], "reason": "jump"} and blind["pred"] is None
    assert [l["status"] for l in blind["links"] if l["id"] == "east>unoq:ble"] == ["blind"]
    assert at(states, 18)["health"]["status"] == "ok" and at(states, 18)["pred"]["kind"] == "none"
    assert [(e["kind"], e["info"]) for e in events[2:]] == [("blind_on", {"link": "east>unoq:ble"}),
                                                            ("blind_off", {"link": "east>unoq:ble"})]
    assert 8.0 <= events[2]["t"] <= 9.5    # 3 s after the 1 s median crossed 6 dB


def test_jump_rule_skips_a_steady_drop_below_base_but_not_an_unsteady_one():
    steady, _ = states_of(jump(-9))
    assert {s["health"]["status"] for s in steady} == {"ok"}          # a steady drop is an object, not a broken link
    shaky, events = states_of(jump(-11, wobble_db=4))
    assert at(shaky, 11)["health"]["reason"] == "jump" and "blind_on" in kinds(events)


def test_jump_rule_is_off_with_someone_there_or_the_router_away():
    with_person = dict(jump(+9), person=[{"t": 0, "x": 0.5, "y": 0.5}])
    away = dict(jump(+9), router=[{"t": 0, "spot": "S-W30"}])
    for path in (with_person, away):
        assert {s["health"]["status"] for s in states_of(path)[0]} == {"ok"}


def test_removed_tray_disappears_within_about_a_second_with_a_person_present():
    states, events = run("tray_removed")
    assert at(states, 13.9)["objects"] and at(states, 13.9)["pred"]["kind"] == "person"
    assert at(states, 14.5)["objects"]                      # its link is still coming down
    gone = at(states, 15.1)
    assert gone["objects"] == [] and set(gone["xray"]["static_db"]) == {0.0}
    assert gone["pred"]["kind"] == "person" and gone["pred"]["zone"] == 2
    off = next(e["t"] for e in events if e["kind"] == "object_off")
    assert 14.9 <= off <= 15.1
    assert max(at(states, 13)["xray"]["static_db"]) > 5     # the static picture did build up with the person there


def _wifi_drop(s):
    return next((l["drop_db"] for l in s["links"] if l["id"] == "pi5>unoq:wifi"), None)


def test_advice_only_while_the_wifi_link_drops_3_db_or_more():
    # Section 6: the same tray, light (under 3 dB on the router link) and heavy.
    def tray(drop_db):
        path = {"name": "t", "duration_s": 14, "person": None,
                "objects": [{"x": 1.0, "y": 0.2, "drop_db": drop_db, "t_on": 2}]}
        return [m for m in state.run(path) if m["type"] == "state"]

    light, heavy = at(tray(2.0), 12), at(tray(8.0), 12)
    assert light["objects"] and _wifi_drop(light) < 3 and light["advice"] is None
    assert _wifi_drop(heavy) >= 3 and heavy["advice"]


def test_no_wifi_row_or_a_null_drop_means_no_advice():
    path = {"name": "t", "duration_s": 14, "person": None, "objects": [{"x": 1.0, "y": 0.2, "drop_db": 8, "t_on": 2}]}
    brain = state.Brain(path)
    obj = [{"x": 1.0, "y": 0.2, "drop_db": 8, "t_on": 0.0}]
    for links in ([], [{"id": "pi5>unoq:wifi", "drop_db": None}], [{"id": "pi5>unoq:wifi", "drop_db": 2.9}]):
        brain.advice = None
        brain._advise(10.0, obj, "S-home", fake.NODES, links)
        assert brain.advice is None, links
    brain._advise(10.0, obj, "S-home", fake.NODES, [{"id": "pi5>unoq:wifi", "drop_db": 3.0}])
    assert brain.advice
    brain._advise(10.1, obj, "S-home", fake.NODES, [{"id": "pi5>unoq:wifi", "drop_db": 1.0}])
    assert brain.advice is None   # the link recovered, so the advice goes, as in the brain


def test_reset_sends_the_reset_event_and_the_template_recap():
    brain = state.Brain(fake.load_path("demo"))
    msgs = []
    for m in state.run(brain.path, brain=brain):
        msgs.append(m)
        if m["type"] == "state" and m["t"] == 60.0:
            brain.command({"cmd": "reset"})
    encode = encoder(1763149500000)
    assert all(set(errors(json.loads(encode(m)))) <= UNMEASURED for m in msgs)
    events = [m for m in msgs if m["type"] == "event"]
    reset = next(e for e in events if e["kind"] == "reset")
    after = next(m for m in msgs if m["type"] == "state" and m["t"] > 60.0)
    recap = after["narration"]
    assert recap["event_id"] == reset["id"] and recap["source"] == "template"
    assert recap["text"].startswith("Someone ") and len(recap["text"].split()) <= 45
    # the next reset only tells what happened since this one
    brain.command({"cmd": "reset"})
    assert brain.narration is None or brain.narration["text"] != recap["text"]


def test_lesson_trains_live_then_the_radio_carries_on_without_the_camera():
    states, events = run("lesson")
    during, after, unplugged = at(states, 14), at(states, 25), at(states, 40)
    assert during["model"]["trained"] is False and during["pred"] is None
    assert during["model"]["training"]["sessions"] == ["lesson"] and 0.4 <= during["model"]["training"]["progress"] <= 0.6
    assert during["teacher"]["present"] is True                       # the camera is labelling the person
    assert after["model"]["trained"] is True and after["model"]["training"] is None and after["pred"]["zone"] == 4
    assert unplugged["cam"] == "off" and unplugged["teacher"] is None and unplugged["pred"]["zone"] == 3
    assert kinds(events)[:2] == ["baseline_done", "trained"] and "cam_off" in kinds(events)
