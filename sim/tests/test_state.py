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
    assert (after["checkin"], after["narration"], after["advice"]) == (None, None, None)
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
