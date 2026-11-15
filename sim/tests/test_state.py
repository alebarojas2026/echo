import json

import pytest

from contracts.check import errors
from narrator import narrate
from sim import fake, state
from sim.tests.conftest import schema_fits
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


# The schema in contracts/ goes with the layout in radio/nodes.json (it lists the links), so this one
# runs on that file's layout, not on both.
@pytest.mark.parametrize("name", sorted(p.stem for p in fake.PATHS_DIR.glob("*.json")))
def test_every_message_passes_the_contract_checker(name):
    encode = encoder(1763149500000)
    path = fake.load_path(name)
    # A path that arms itself sends `armed` and `tamper`, which the schema doesn't list yet (#440, #541).
    waived = ARMED_NOT_IN_SCHEMA + TAMPER_NOT_IN_SCHEMA if path.get("commands") else ()
    for m in state.run(path):
        for err in errors(json.loads(encode(m))):
            assert err in UNMEASURED or any(word in err for word in waived), (name, m["t"], err)


def test_starts_with_no_readings_no_baseline_and_no_model(each_layout):
    states, events = run("zone_tour")
    first = states[0]
    assert set(first) == STATE_KEYS and len(states) == 32 * 10
    assert (first["links"], first["xray"], first["pred"], first["objects"]) == ([], None, None, [])
    assert (first["advice"], first["checkin"], first["narration"], first["alert"]) == (None, None, None, IDLE)
    assert first["model"] == {"trained": False, "ver": None, "train_s": None, "ms_per_decision": None,
                              "windows": 0, "train_sessions": [], "training": None}
    assert first["board"] == {"cpu_temp_c": None, "cpu_mhz": None, "cpu_pct": None}
    early = at(states, 0.5)   # readings, but no baseline yet
    assert len(early["links"]) == len(fake.LINKS) and early["xray"] is None and early["pred"] is None
    assert {(l["base_dbm"], l["drop_db"], l["expected_hz"], l["status"]) for l in early["links"]} == {(None, None, None, "ok")}
    assert isinstance(early["links"][0]["dbm"], float)
    assert [(e["t"], e["kind"]) for e in events[:3]] == [(1.0, "baseline_done"), (2.0, "trained"), (2.0, "enter")]


def test_after_baseline_and_training(each_layout):
    states, _ = run("zone_tour")
    based = at(states, 1.5)
    cells = each_layout.grid["w"] * each_layout.grid["h"]   # the square: 10 x 10; the strip: 16 x 12
    assert len(based["xray"]["moving_db"]) == len(based["xray"]["static_db"]) == cells and based["pred"] is None
    assert all(isinstance(l["base_dbm"], float) and l["expected_hz"] == 15 for l in based["links"])
    s = at(states, 4)
    assert s["model"] == {"trained": True, "ver": "sim", "train_s": None, "ms_per_decision": None,
                          "windows": 0, "train_sessions": [], "training": None}
    assert set(s["links"][0]) == {"id", "dbm", "base_dbm", "drop_db", "rate_hz", "expected_hz", "status", "why"}
    line = json.loads(encoder(1763149500000)(s))
    assert (line["v"], line["src"], line["t"]) == (2, "sim", 1763149504000)


WHY_AT_THE_FIRST_STOP = {"square": ["west>pi5:ble"], "strip": ["west>unoq:ble", "west>pi5b:ble"]}


def test_zone_tour_predictions_events_and_narration(each_layout):
    states, events = run("zone_tour")
    stops = [each_layout.zone(f"tour{i}") for i in (1, 2, 3, 4)]   # the square: 3, 4, 2, 1; the strip: 1, 2, 1, 2
    assert [at(states, t)["pred"]["zone"] for t in (4, 11, 18, 25)] == stops
    s = at(states, 4)
    assert s["pred"]["kind"] == "person" and s["pred"]["motion"] == "still" and s["pred"]["still_s"] > 2
    assert s["pred"]["why"] == WHY_AT_THE_FIRST_STOP[each_layout.name] and abs(sum(s["pred"]["probs"]) - 1) < 1e-9
    gone = at(states, 30)["pred"]
    assert (gone["kind"], gone["present"], gone["zone"], gone["zone_set"], gone["motion"]) == ("none", False, 0, [], None)
    assert kinds(events)[2:] == ["enter", "zone_change", "zone_change", "zone_change", "exit"]
    told = at(states, 10)["narration"]
    assert (told["text"], told["source"], told["event_id"]) == (narrate.template("zone_change", {"zone": stops[1]}), "template", events[3]["id"])
    assert all(len(text.split()) <= 16 for text in state.SENTENCES.values())


def test_alert_counts_then_fires_and_a_wave_clears_it(each_layout):
    states, events = run("wave_checkin")
    assert at(states, 6)["alert"]["state"] == "counting" and at(states, 6)["alert"]["limit_s"] == 10
    assert at(states, 13)["alert"]["state"] == "check_on" and at(states, 13)["alert"]["zone"] == each_layout.still_zone()
    assert at(states, 16)["alert"]["state"] == "counting" and at(states, 16)["checkin"]["link"] == "pi5>unoq:wifi"
    assert at(states, 24.5)["alert"] == IDLE
    assert kinds(events)[2:6] == ["enter", "alert_on", "checkin", "alert_off"]


def test_dropped_link_goes_blind_and_recovers(each_layout):
    states, events = run("dropped_link")
    assert at(states, 10.5)["health"]["status"] == "ok"  # the 2 s rate has not fallen far enough yet
    assert at(states, 12.5)["health"]["status"] == "degraded" and at(states, 12.5)["pred"]
    blind = at(states, 15)
    # east's links go blind, except the one Pi B hears (east>pi5b:ble on the strip): that one never is
    east = sorted(fake.link_id(*l) for l in fake.LINKS if l[0] == "east" and l[1] != "pi5b")
    assert blind["health"]["status"] == "blind" and blind["health"]["blind"] == east and blind["pred"] is None
    assert blind["xray"]["n_links"] == len(fake.LINKS) - 2
    assert at(states, 28)["health"]["status"] == "ok" and at(states, 28)["pred"]["zone"] == each_layout.zone("tour4")
    assert kinds(events).count("blind_on") == 2 and kinds(events).count("blind_off") == 2
    assert kinds(events).count("enter") == 1 and "exit" not in kinds(events)  # going blind is not leaving


def test_camera_unplug_keeps_predicting(each_layout):
    states, events = run("camera_unplug")
    assert at(states, 20)["cam"] == "off" and at(states, 20)["teacher"] is None
    assert at(states, 20)["pred"]["zone"] == each_layout.zone("tour3")
    assert "cam_off" in kinds(events)


ADVICE = {"square": ("S-W30", [-0.3, 0.0], 0.02, "west"), "strip": ("S-E30", [0.3, 0.0], -0.08, "east")}


def test_tray_gets_advice_and_the_router_move_gets_a_result(each_layout):
    states, events = run("router_move")
    tray = at(states, 40)
    assert tray["pred"]["kind"] == "object" and tray["objects"][0]["near"] == "pi5"
    if each_layout.name == "square":
        grid = tray["xray"]["static_db"]
        assert {(i % 10, i // 10) for i in range(100) if grid[i] == max(grid)} == {(4, 1), (5, 1)}  # T1 is between two cells
    advice = tray["advice"]
    assert at(states, 29)["advice"] is None and at(states, 31)["advice"]  # 5 s after the tray lands at 25 s
    spot, move, change, way = ADVICE[each_layout.name]
    assert (advice["to_spot"], advice["move_m"], advice["dist_change_m"], advice["link"]) == (spot, move, change, "pi5>unoq:wifi")
    assert fake.load_path("router_move")["router"][1]["spot"] == spot   # the path moves the router where the advice says
    assert advice["text"].endswith(f"Move the router 30 cm {way}.") and advice["near"] == "pi5"
    base = fake.baseline("pi5", "unoq", "wifi")
    assert abs(advice["before_dbm"] - (base - 10)) < 2 and advice["after_dbm"] is None and "pi5>unoq:wifi" in advice["why"]
    moved = at(states, 48)   # router moved at 45 s
    assert moved["router"] == spot and moved["pred"] is None and moved["advice"]["after_dbm"] is None
    done = at(states, 52)["advice"]
    assert abs(done["before_dbm"] - advice["before_dbm"]) < 1.5   # frozen at the move
    assert done["after_dbm"] - done["before_dbm"] > 4   # the move cleared the link
    assert at(states, 70)["advice"] is None             # router home, tray gone
    assert kinds(events)[2:] == ["object_on", "advice", "router_moved", "advice_result", "object_off", "router_home"]
    result = next(e for e in events if e["kind"] == "advice_result")["info"]
    assert (result["before_dbm"], result["after_dbm"]) == (done["before_dbm"], done["after_dbm"])


def test_demo_walks_the_whole_story_in_order(each_layout):
    _, events = run("demo")
    story = ["baseline_done", "trained", "enter", "checkin", "object_on", "advice", "router_moved", "advice_result",
             "router_home", "cam_off", "alert_on", "checkin", "alert_off", "blind_on", "blind_off", "exit"]
    seen = iter(kinds(events))
    assert all(kind in seen for kind in story), kinds(events)   # each one appears, in this order
    assert len({e["id"] for e in events}) == len(events)


def test_reset_alert_and_reset_commands(each_layout):
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
    recap = after["narration"]["text"]   # the recap, not the last sentence ("Someone visited the Bathroom zone.")
    assert recap.startswith("Someone ") and each_layout.names[each_layout.still_zone()].lower() in recap.lower()
    assert after["pred"]["still_s"] < 0.5 and after["alert"]["still_s"] < 0.5


def test_object_far_from_every_node_has_no_near_but_still_gets_advice(square):
    middle = {"name": "m", "duration_s": 12, "person": None, "objects": [{"x": 1.0, "y": 1.0, "drop_db": 8, "t_on": 2}]}
    msgs = list(state.run(middle))
    states, events = [m for m in msgs if m["type"] == "state"], [m for m in msgs if m["type"] == "event"]
    encode = encoder(1763149500000)
    assert not schema_fits(square) or all(set(errors(json.loads(encode(m)))) <= UNMEASURED for m in msgs)
    s = at(states, 10)
    assert s["objects"][0]["near"] is None and s["advice"]["near"] is None
    assert s["advice"]["text"] == ("On the router's link, an obstruction is blocking its link to the receiver. "
                                   "Move the router 30 cm west.")
    assert isinstance(s["advice"]["before_dbm"], float)
    assert [(e["kind"], e["info"].get("node", "-")) for e in events[2:]] == [("object_on", "-"), ("advice", "-")]   # no node to name
    assert at(states, 5)["narration"]["text"] == narrate.template("object_on", {})   # the narrator's sentence, no node
    assert state.near(fake.NODES, (1.0, 0.2)) == "pi5" and state.near(fake.NODES, (1.0, 0.6)) is None


# ---- the three section 6 rules the fake brain follows since the contract update ----

def states_of(path):
    msgs = list(state.run(path))
    return [m for m in msgs if m["type"] == "state"], [m for m in msgs if m["type"] == "event"]


def test_one_moving_flicker_does_not_reset_the_still_timer(each_layout):
    states, events = run("still_flicker")
    assert at(states, 7.1)["pred"]["motion"] == "moving"            # the wrong decision is shown as it is
    assert at(states, 7.6)["pred"]["still_s"] > at(states, 6.9)["pred"]["still_s"] > 4   # and the timer runs on
    fired = next(e["t"] for e in events if e["kind"] == "alert_on")
    plain = dict(fake.load_path("still_flicker"), flickers=[])
    assert fired == next(e["t"] for e in states_of(plain)[1] if e["kind"] == "alert_on")
    assert 11.0 <= fired <= 12.0                                    # 10 s after standing still begins


def test_five_moving_decisions_in_a_row_do_reset_it(each_layout):
    long = dict(fake.load_path("still_flicker"), flickers=[{"t_on": 7.0, "t_off": 7.6}])
    states, events = states_of(long)
    assert at(states, 7.35)["pred"]["still_s"] > 4 and at(states, 7.7)["pred"]["still_s"] < 0.3
    assert not [e for e in events if e["kind"] == "alert_on"]       # only 8.4 s left before they walk out


def test_another_zone_resets_the_still_timer_once_it_holds_the_majority(square):
    hop = {"name": "h", "duration_s": 12, "person": [{"t": 0, "x": 0.9, "y": 0.5}, {"t": 6, "x": 0.9, "y": 0.5},
                                                      {"t": 6.2, "x": 1.1, "y": 0.5}]}   # a short step, zone 3 to 4
    states, _ = states_of(hop)
    assert at(states, 6.4)["pred"]["zone"] == 4 and at(states, 6.4)["pred"]["still_s"] > 3   # not yet the majority
    assert at(states, 6.9)["pred"]["still_s"] < 0.5
    assert at(states, 6.4)["alert"] == IDLE and at(states, 8)["alert"]["zone"] == 4


def jump(db, **extra):
    return {"name": "j", "duration_s": 20, "person": None,
            "jumps": [{"link": "east>unoq:ble", "db": db, "t_on": 5, "t_off": 12, **extra}]}


def test_jump_rule_blinds_a_link_that_sits_off_base(square):
    states, events = states_of(jump(+9))   # above base: never an object
    assert at(states, 7)["health"]["status"] == "ok"
    blind = at(states, 10)
    assert blind["health"] == {"status": "blind", "blind": ["east>unoq:ble"], "reason": "jump"} and blind["pred"] is None
    assert [l["status"] for l in blind["links"] if l["id"] == "east>unoq:ble"] == ["blind"]
    assert at(states, 18)["health"]["status"] == "ok" and at(states, 18)["pred"]["kind"] == "none"
    assert [(e["kind"], e["info"]) for e in events[2:]] == [("blind_on", {"link": "east>unoq:ble"}),
                                                            ("blind_off", {"link": "east>unoq:ble"})]
    assert 8.0 <= events[2]["t"] <= 9.5    # 3 s after the 1 s median crossed 6 dB


def test_jump_rule_skips_a_steady_drop_below_base_but_not_an_unsteady_one(square):
    steady, _ = states_of(jump(-9))
    assert {s["health"]["status"] for s in steady} == {"ok"}          # a steady drop is an object, not a broken link
    shaky, events = states_of(jump(-11, wobble_db=4))
    assert at(shaky, 11)["health"]["reason"] == "jump" and "blind_on" in kinds(events)


def test_jump_rule_is_off_with_someone_there_or_the_router_away(square):
    with_person = dict(jump(+9), person=[{"t": 0, "x": 0.5, "y": 0.5}])
    away = dict(jump(+9), router=[{"t": 0, "spot": "S-W30"}])
    for path in (with_person, away):
        assert {s["health"]["status"] for s in states_of(path)[0]} == {"ok"}


def test_removed_tray_disappears_within_about_a_second_with_a_person_present(each_layout):
    states, events = run("tray_removed")
    assert at(states, 13.9)["objects"] and at(states, 13.9)["pred"]["kind"] == "person"
    assert at(states, 14.5)["objects"]                      # its link is still coming down
    gone = at(states, 15.1)
    assert gone["objects"] == [] and set(gone["xray"]["static_db"]) == {0.0}
    assert gone["pred"]["kind"] == "person" and gone["pred"]["zone"] == each_layout.zone("tour3")
    off = next(e["t"] for e in events if e["kind"] == "object_off")
    assert 14.9 <= off <= 15.1
    assert max(at(states, 13)["xray"]["static_db"]) > 5     # the static picture did build up with the person there


def _wifi_drop(s):
    return next((l["drop_db"] for l in s["links"] if l["id"] == "pi5>unoq:wifi"), None)


def test_advice_only_while_the_wifi_link_drops_3_db_or_more(square):
    # Section 6: the same tray, light (under 3 dB on the router link) and heavy.
    def tray(drop_db):
        path = {"name": "t", "duration_s": 14, "person": None,
                "objects": [{"x": 1.0, "y": 0.2, "drop_db": drop_db, "t_on": 2}]}
        return [m for m in state.run(path) if m["type"] == "state"]

    light, heavy = at(tray(2.0), 12), at(tray(8.0), 12)
    assert light["objects"] and _wifi_drop(light) < 3 and light["advice"] is None
    assert _wifi_drop(heavy) >= 3 and heavy["advice"]


def test_no_wifi_row_or_a_null_drop_means_no_advice(square):
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


def test_reset_sends_the_reset_event_and_the_template_recap(each_layout):
    brain = state.Brain(fake.load_path("demo"))
    msgs = []
    for m in state.run(brain.path, brain=brain):
        msgs.append(m)
        if m["type"] == "state" and m["t"] == 60.0:
            brain.command({"cmd": "reset"})
    encode = encoder(1763149500000)
    assert not schema_fits(each_layout) or all(set(errors(json.loads(encode(m)))) <= UNMEASURED for m in msgs)
    events = [m for m in msgs if m["type"] == "event"]
    reset = next(e for e in events if e["kind"] == "reset")
    after = next(m for m in msgs if m["type"] == "state" and m["t"] > 60.0)
    recap = after["narration"]
    assert recap["event_id"] == reset["id"] and recap["source"] == "template"
    assert recap["text"].startswith("Someone ") and len(recap["text"].split()) <= 45
    # the next reset only tells what happened since this one
    brain.command({"cmd": "reset"})
    assert brain.narration is None or brain.narration["text"] != recap["text"]


# Section 5 and 6, Armed. The schema in contracts/ doesn't list `armed` or its events yet (its issue is
# open), so these are the only schema errors allowed here.
ARMED_NOT_IN_SCHEMA = ("armed", "disarmed", "intrusion", "passed_by", "Unevaluated properties are not allowed ('armed' was unexpected)")
TAMPER_NOT_IN_SCHEMA = ("tamper", "tamper_cleared")   # the same for Tamper (#541)


def test_armed_mode_raises_one_intrusion_per_arrival(each_layout):
    brain = state.Brain(fake.load_path("arrival"))
    msgs = []
    for m in state.run(brain.path, brain=brain):
        msgs.append(m)
        if m["type"] == "state" and m["t"] == 3.0:
            brain.command({"cmd": "arm", "args": {"on": True}})
        if m["type"] == "state" and m["t"] == 25.0:
            brain.command({"cmd": "reset"})
    events = [(m["t"], m["kind"], m["info"]) for m in msgs if m["type"] == "event"]
    kinds = [k for _, k, _ in events]
    assert kinds.count("armed") == 1 and kinds.count("intrusion") == 1 and kinds.count("disarmed") == 1
    t_in = next(t for t, k, _ in events if k == "enter")
    t_intrusion, _, info = next(e for e in events if e[1] == "intrusion")
    assert info == {"zone": each_layout.zone("tour1")} and 3.0 <= t_intrusion - t_in <= 4.0   # still there 3 s after appearing
    assert "passed_by" not in kinds
    assert at([m for m in msgs if m["type"] == "state"], 20)["armed"] is True
    assert "armed" not in at([m for m in msgs if m["type"] == "state"], 26)   # missing means false
    encode = encoder(1763149500000)
    for m in msgs if schema_fits(each_layout) else []:
        for err in errors(json.loads(encode(m))):
            assert err in UNMEASURED or any(word in err for word in ARMED_NOT_IN_SCHEMA), err


def armed_events(name, **more):
    msgs = list(state.run({**fake.load_path(name), **more}))
    return [(m["t"], m["kind"], m["info"]) for m in msgs if m["type"] == "event"
            and m["kind"] in ("armed", "intrusion", "passed_by", "disarmed")]


def test_walking_through_while_armed_is_passed_by_and_staying_is_an_intrusion(each_layout):
    first = each_layout.zone("tour1")
    through = armed_events("passed_by")                                 # crosses the area in 1.5 s
    assert [k for _, k, _ in through] == ["armed", "passed_by", "disarmed"]
    t, _, info = through[1]
    assert info == {"zone": first} and 11.5 <= t <= 12.5                # said once they are gone, with where they appeared
    stay = armed_events("step_in")                                      # steps in at 10 s and stands for 6 s
    assert [k for _, k, _ in stay] == ["armed", "intrusion", "disarmed"]
    t, _, info = stay[1]
    assert info == {"zone": first} and 13.0 <= t <= 14.5                # about 3 to 4 s after stepping in
    never = armed_events("passed_by", commands=[])                      # not armed: neither
    assert never == []


def test_nothing_is_said_while_blind_and_the_armed_wait_starts_when_the_sensor_sees_again():
    east = [{"node": "east", "t_on": 5, "t_off": 20}]                   # a beacon is dead when they step in at 10 s
    person = [{"t": 0, "x": None}, {"t": 10, "x": 0.5, "y": 0.5}, {"t": 29.5, "x": 0.5, "y": 0.5}, {"t": 29.6, "x": None}]
    events = armed_events("step_in", outages=east, person=person, duration_s=32,
                          commands=[{"t": 3, "cmd": "arm", "args": {"on": True}}])
    said = [(t, k) for t, k, _ in events if k in ("intrusion", "passed_by")]
    assert len(said) == 1 and said[0][1] == "intrusion" and 25 < said[0][0] < 29   # blind until about 23 s, then 3 s


def test_no_intrusion_while_blind_or_disarmed():
    brain = state.Brain(fake.load_path("arrival"))
    kinds = [m["kind"] for m in state.run(brain.path, brain=brain) if m["type"] == "event"]
    assert "intrusion" not in kinds and "armed" not in kinds                       # never armed
    brain = state.Brain(fake.load_path("arrival"))
    brain._arm(0.0, True)
    brain.recent.extend([("person", 3, False)] * 10)
    brain._intrusion(5.0, None)                                                     # pred null: blind or not trained
    assert not any(e["kind"] == "intrusion" for e in brain.events)


def tamper_run(commands=None, **more):
    path = {**fake.load_path("tamper"), **more}
    if commands is not None:
        path["commands"] = commands
    msgs = list(state.run(path))
    events = [(m["t"], m["kind"], m["info"]) for m in msgs if m["type"] == "event"]
    return [m for m in msgs if m["type"] == "state"], events, msgs


def test_tamper_path_armed_east_goes_silent_then_comes_back():
    states, events, msgs = tamper_run()
    told = [(t, k, i) for t, k, i in events if k in ("armed", "tamper", "tamper_cleared", "disarmed", "intrusion")]
    assert told == [(3.0, "armed", {}), (13.0, "tamper", {"node": "east"}),          # 3 s after east stopped at 10 s
                    (22.0, "tamper_cleared", {"node": "east"}), (36.0, "disarmed", {})]   # 2 s after it is back at 20 s
    assert "tamper" not in at(states, 12) and "tamper" not in at(states, 23)          # absent when no node is listed
    during = at(states, 16)
    assert during["tamper"] == ["east"] and during["armed"] is True
    assert during["health"]["status"] == "blind" and during["pred"] is None           # blind, and tamper still said
    assert during["narration"]["text"] and len(during["narration"]["text"].split()) <= 16
    encode = encoder(1763149500000)
    not_in_schema = ARMED_NOT_IN_SCHEMA + TAMPER_NOT_IN_SCHEMA
    for m in msgs:
        for err in errors(json.loads(encode(m))):
            assert err in UNMEASURED or any(word in err for word in not_in_schema), err


def test_tamper_needs_armed_and_disarm_or_reset_clears_it():
    _, events, _ = tamper_run(commands=[])                                            # never armed: only blind
    assert not any(k.startswith("tamper") for _, k, _ in events) and any(k == "blind_on" for _, k, _ in events)
    for cmd in ({"cmd": "arm", "args": {"on": False}}, {"cmd": "reset"}):             # east is still unplugged at 16 s
        states, events, _ = tamper_run(commands=[{"t": 3, "cmd": "arm", "args": {"on": True}}, {"t": 16, **cmd}])
        kinds = [(t, k) for t, k, _ in events if k in ("tamper", "tamper_cleared", "disarmed")]
        assert kinds == [(13.0, "tamper"), (16.0, "disarmed"), (16.0, "tamper_cleared")]
        assert "tamper" not in at(states, 17)
    # armed with east already silent: raised at once
    _, events, _ = tamper_run(commands=[{"t": 15, "cmd": "arm", "args": {"on": True}}])
    assert [(t, k) for t, k, _ in events if k.startswith("tamper")] == [(15.0, "tamper"), (22.0, "tamper_cleared")]


def test_a_person_stepping_in_while_a_device_is_silent_raises_no_intrusion():
    person = [{"t": 0, "x": None}, {"t": 14, "x": 0.5, "y": 0.5}, {"t": 18, "x": 0.5, "y": 0.5}, {"t": 18.1, "x": None}]
    _, events, _ = tamper_run(person=person)
    assert [k for _, k, _ in events if k in ("tamper", "intrusion")] == ["tamper"]    # blind: the tamper is what is said


def test_a_link_pi_b_hears_degrades_health_but_never_blinds_it(square, monkeypatch):
    monkeypatch.setitem(fake.NODES, "pi5b", (0.5, 0.6))
    monkeypatch.setattr(fake, "LINKS", fake.LINKS + [("west", "pi5b", "ble")])
    path = {"name": "t", "duration_s": 12, "person": None, "outages": [{"link": "west>pi5b:ble", "t_on": 3, "t_off": 12}]}
    brain = state.Brain(path)
    brain.readings["west>pi5b:ble"] = state.deque()
    states = [m for m in state.run(path, brain=brain) if m["type"] == "state"]
    late = at(states, 10)
    assert late["health"]["status"] == "degraded" and late["health"]["blind"] == []
    assert next(l for l in late["links"] if l["id"] == "west>pi5b:ble")["status"] == "stale"
    assert late["pred"] is not None                                   # predictions carry on


def test_the_demo_alerts_once_and_only_in_the_alert_zone(each_layout):
    # Both of the strip's zones alert after 10 s, so the steps about in the calm zone must reset the
    # still timer (5 moving decisions in a row): only the stand in the alert zone raises it.
    _, events = run("demo")
    assert [e["info"]["zone"] for e in events if e["kind"] == "alert_on"] == [each_layout.still_zone()]


def test_the_fake_brain_sees_nobody_in_a_crowded_aisle(each_layout):
    states, events = run("aisle")
    assert not any(s["pred"] and s["pred"]["present"] for s in states)
    assert not {"enter", "intrusion", "alert_on"} & set(kinds(events))
