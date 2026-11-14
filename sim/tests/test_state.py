import json

import pytest

from contracts.check import errors
from sim import fake, state
from sim.wire import encoder

STATE_KEYS = {"type", "t", "cam", "router", "links", "health", "pred", "objects", "xray", "alert", "checkin",
              "advice", "narration", "teacher", "model", "board"}


def run(name):
    msgs = list(state.run(fake.load_path(name)))
    return [m for m in msgs if m["type"] == "state"], [m for m in msgs if m["type"] == "event"]


def at(states, t):
    return min(states, key=lambda s: abs(s["t"] - t))


def kinds(events):
    return [e["kind"] for e in events]


def test_state_has_the_contract_fields_ten_times_a_second():
    states, _ = run("zone_tour")
    assert all(set(s) == STATE_KEYS for s in states)
    assert len(states) == 32 * 10
    s = at(states, 4)
    assert len(s["links"]) == 6 and set(s["links"][0]) == {
        "id", "dbm", "base_dbm", "drop_db", "rate_hz", "expected_hz", "status", "why"}
    assert len(s["xray"]["moving_db"]) == len(s["xray"]["static_db"]) == 100
    line = json.loads(encoder(1763149500000)(s))
    assert (line["v"], line["src"], line["t"]) == (2, "sim", 1763149504000)


@pytest.mark.parametrize("name", sorted(p.stem for p in fake.PATHS_DIR.glob("*.json")))
def test_every_message_passes_the_contract_checker(name):
    encode = encoder(1763149500000)
    for m in state.run(fake.load_path(name)):
        assert errors(json.loads(encode(m))) == [], (name, m["t"])


def test_nothing_measured_is_zero_and_narration_follows_events():
    states, events = run("zone_tour")
    s = at(states, 10)
    assert s["model"] == {"trained": True, "ver": "sim", "train_s": 0, "ms_per_decision": 0, "windows": 0,
                          "train_sessions": [], "training": None}
    assert set(s["board"].values()) == {0} and s["advice"] is None
    assert s["narration"]["text"] == "Someone moved to zone 4." and s["narration"]["source"] == "template"
    assert s["narration"]["event_id"] == events[1]["id"]
    assert all(len(text.split()) <= 16 for text in state.SENTENCES.values())


def test_zone_tour_predictions_and_events():
    states, events = run("zone_tour")
    assert [at(states, t)["pred"]["zone"] for t in (4, 11, 18, 25)] == [3, 4, 2, 1]
    s = at(states, 4)
    assert s["pred"]["kind"] == "person" and s["pred"]["motion"] == "still" and s["pred"]["still_s"] > 2
    assert s["pred"]["why"] == ["west>pi5:ble"] and abs(sum(s["pred"]["probs"]) - 1) < 1e-9
    assert at(states, 30)["pred"]["kind"] == "none"
    assert kinds(events) == ["enter", "zone_change", "zone_change", "zone_change", "exit"]


def test_alert_counts_then_fires_and_a_wave_clears_it():
    states, events = run("wave_checkin")
    assert at(states, 6)["alert"]["state"] == "counting" and at(states, 6)["alert"]["limit_s"] == 10
    assert at(states, 13)["alert"]["state"] == "check_on"
    assert at(states, 16)["alert"]["state"] == "counting" and at(states, 16)["checkin"]["link"] == "pi5>unoq:wifi"
    assert kinds(events)[:4] == ["enter", "alert_on", "checkin", "alert_off"]


def test_dropped_link_goes_blind_and_recovers():
    states, events = run("dropped_link")
    assert at(states, 10.5)["health"]["status"] == "ok"  # the 2 s rate has not fallen far enough yet
    assert at(states, 12.5)["health"]["status"] == "degraded" and at(states, 12.5)["pred"]
    blind = at(states, 15)
    assert blind["health"]["status"] == "blind" and blind["pred"] is None and blind["xray"]["n_links"] == 4
    assert at(states, 28)["health"]["status"] == "ok" and at(states, 28)["pred"]["zone"] == 1
    assert kinds(events).count("blind_on") == 2 and kinds(events).count("blind_off") == 2


def test_camera_unplug_tray_and_router_move():
    states, events = run("camera_unplug")
    assert at(states, 20)["cam"] == "off" and at(states, 20)["teacher"] is None and at(states, 20)["pred"]["zone"] == 2
    assert "cam_off" in kinds(events)
    states, events = run("router_move")
    tray = at(states, 40)
    assert tray["pred"]["kind"] == "object" and tray["objects"][0]["near"] == "pi5"
    grid = tray["xray"]["static_db"]
    peaks = {(i % 10, i // 10) for i in range(100) if grid[i] == max(grid)}
    assert peaks == {(4, 1), (5, 1)}  # T1 (1.0, 0.2) sits on the line between these two cells
    assert at(states, 50)["router"] == "S-W30" and at(states, 50)["pred"] is None
    assert kinds(events) == ["object_on", "router_moved", "object_off", "router_home"]


def test_reset_alert_command():
    brain = state.Brain(fake.load_path("stand_still"))
    states = []
    for m in state.run(brain.path, brain=brain):
        if m["type"] == "state":
            states.append(m)
            if m["t"] == 13.0:
                brain.command({"cmd": "reset_alert"})
    assert at(states, 12.9)["alert"]["state"] == "check_on" and at(states, 13.5)["alert"]["state"] == "counting"
