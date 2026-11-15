"""The sim on a layout with one zone and three devices (layouts/spot.json, the gate layout)."""
import json

from sim import fake, lesson, state
from sim.tests.conftest import LAYOUTS, load, pin


def test_one_zone_covers_the_strip_and_nothing_else():
    lay = load("spot")
    assert lay.zones == {1: 10} and lay.split_x_m is None and lay.names == {1: "At the desk"}
    assert [lay.zone_of(x, y) for x, y in ((0.4, 0.3), (0.0, 0.0), (0.8, 0.6))] == [1, 1, 1]
    assert [lay.zone_of(x, y) for x, y in ((0.4, -0.1), (0.4, 0.7), (-0.1, 0.3), (0.9, 0.3))] == [0, 0, 0, 0]
    assert lay.tour() == [1] and lay.still_zone() == 1 and lay.calm_zone() == 1     # nowhere else to stand
    assert lay.nodes["pi5b"] == (0.4, -0.2)                                         # a device outside frame.size_m
    assert lay.grid == {"w": 10, "h": 14, "cell_m": 0.125, "origin_m": [-0.2, -0.2]}


def test_the_device_that_gets_unplugged_follows_the_layout():
    assert load("spot").prop_node() == "pi5b"       # the far device: no east beacon here
    assert load("strip").prop_node() == "east" and load("square").prop_node() == "east"
    path = load("spot").resolve({"outages": [{"node": "prop", "t_on": 1, "t_off": 2}], "objects": [{"near": "prop"}]})
    assert path["outages"] == [{"node": "pi5b", "t_on": 1, "t_off": 2}] and path["objects"][0]["y"] == -0.2


def test_every_path_file_plays_on_one_spot_with_six_links_and_one_zone(monkeypatch):
    pin(monkeypatch, "spot")
    for file in sorted(fake.PATHS_DIR.glob("*.json")):
        events = list(fake.simulate(fake.load_path(str(file)), seed=1))
        links = {e["link"] for e in events if e["type"] == "rssi" and e["tx"] not in ("h", "j")}
        assert links <= {"pi5>unoq:wifi", "pi5>unoq:ble", "pi5b>unoq:ble", "pi5>pi5b:wifi", "pi5>pi5b:ble", "pi5b>pi5:ble"}, file.name
        assert {e["zone"] for e in events if e["type"] == "label"} <= {0, 1, None}, file.name


def test_a_person_on_the_spot_drops_the_lines_to_pi_b_and_not_the_desks(monkeypatch):
    lay = pin(monkeypatch, "spot")
    at = lay.centres[1]
    drops = {fake.link_id(tx, rx, kind): fake.person_drop(at, lay.nodes[tx], lay.nodes[rx]) for tx, rx, kind in lay.links}
    assert all(drops[k] > 6 for k in drops if "pi5b" in k) and all(drops[k] < 1 for k in drops if "pi5b" not in k)


def test_the_lesson_on_one_spot_has_no_sides_and_no_dead_band(monkeypatch):
    lay = pin(monkeypatch, "spot")
    path = lesson.path(lay)
    assert path["dead_band_m"] == 0.0 and "left" not in path["about"] and "right" not in path["about"]
    assert {zone for _, _, zone in lesson.stands(lay)} == {1}
    labels = [e for e in fake.simulate(path, seed=2) if e["type"] == "label"]
    assert not any(e["clipped"] for e in labels) and {e["zone"] for e in labels} == {0, 1}
    assert all(e["foot_m"] is None for e in labels)                                  # the desk view has no foot point
    doc = json.loads((LAYOUTS / "spot.json").read_text(encoding="utf-8"))
    assert "zone_split_x_m" not in doc["frame"] and len(doc["zones"]) == 1


def test_on_the_gate_the_fake_brain_never_says_move_the_router(monkeypatch):
    lay = pin(monkeypatch, "spot")
    assert lay.presence_line == "pi5>pi5b:wifi"
    for name in ("tray_t1", "router_move", "demo", "thing_left"):
        msgs = list(state.run(fake.load_path(name)))
        advice = [m["advice"] for m in msgs if m["type"] == "state" and m["advice"]]
        # Pi A is cabled to the hub here: whatever blocks a line, nothing names a spot or says to move the router
        assert all(a["to_spot"] is None and a["move_m"] == [0, 0] and a["dist_change_m"] == 0 for a in advice), name
        assert all(a["link"] == "pi5>pi5b:wifi" and "router" not in a["text"].lower() for a in advice), name


def test_the_presence_line_comes_25_times_a_second_and_sits_within_1_db_when_empty(monkeypatch):
    pin(monkeypatch, "spot")
    events = [e for e in fake.simulate({"name": "empty", "duration_s": 20, "person": None}, seed=3) if e["type"] == "rssi"]
    assert [e["t"] for e in events] == sorted(e["t"] for e in events)              # still in time order
    line = [e for e in events if e["link"] == "pi5>pi5b:wifi"]
    assert len(line) == 20 * 25 and max(e["dbm"] for e in line) - min(e["dbm"] for e in line) <= 2   # whole dBm either side
    assert max(b["t"] - a["t"] for a, b in zip(line, line[1:])) <= 0.041
    others = {e["link"] for e in events} - {"pi5>pi5b:wifi"}
    assert len(others) == 5 and all(sum(e["link"] == k for e in events) == 20 * 15 for k in others)   # the rest as before
    # a layout without a presence line is fed exactly as it was
    pin(monkeypatch, "strip")
    strip = [e for e in fake.simulate({"name": "empty", "duration_s": 4, "person": None}, seed=3) if e["type"] == "rssi"]
    assert all(sum(e["link"] == k for e in strip) == 4 * 15 for k in {e["link"] for e in strip})


def test_a_thing_left_in_the_line_for_30_s_is_an_object_with_advice_and_its_removal_shows_the_gain(monkeypatch):
    lay = pin(monkeypatch, "spot")
    path = fake.load_path("thing_left")
    thing = path["objects"][0]
    assert (thing["x"], thing["y"]) == lay.in_the_line() == (0.38, 0.3) and thing["t_off"] - thing["t_on"] == 30
    feed = [e for e in fake.simulate(path, seed=4) if e["type"] == "rssi" and e["link"] == "pi5>pi5b:wifi"]
    level = lambda a, b: sorted(e["dbm"] for e in feed if a <= e["t"] < b)[len([e for e in feed if a <= e["t"] < b]) // 2]   # noqa: E731
    assert level(0, 10) - level(15, 40) == 5 and level(45, 60) == level(0, 10)    # 5 dB down while it stands there
    msgs = list(state.run(path))
    states = [m for m in msgs if m["type"] == "state"]
    t0 = states[0]["t"]
    during = [m for m in states if 16 <= m["t"] - t0 < 40]
    assert all(m["pred"]["present"] is False and m["pred"]["kind"] == "object" and m["pred"]["zone"] == 0 for m in during)
    assert all(m["alert"]["state"] == "none" for m in states)
    advice = during[-1]["advice"]
    assert (advice["link"], advice["to_spot"], advice["move_m"], advice["dist_change_m"]) == ("pi5>pi5b:wifi", None, [0, 0], 0)
    assert advice["after_dbm"] is None and advice["xy_m"] == [0.38, 0.3] and advice["why"] == ["pi5>pi5b:wifi"]
    assert advice["text"] == "Something is standing in the Wi-Fi line from Pi A to Pi B. Take it away to get the signal back."
    kinds = [m["kind"] for m in msgs if m["type"] == "event" and m["kind"] in ("advice", "advice_result", "enter", "intrusion")]
    assert kinds == ["advice", "advice_result"]
    result = next(m for m in msgs if m["type"] == "event" and m["kind"] == "advice_result")
    assert 45 <= result["t"] - t0 <= 47                       # 3 s of readings, starting 2 s after it went
    assert 4 <= result["info"]["after_dbm"] - result["info"]["before_dbm"] <= 6
    shown = [m["advice"] for m in states if m["advice"] and m["advice"]["after_dbm"] is not None]
    assert shown and shown[0]["after_dbm"] == result["info"]["after_dbm"] and states[-1]["advice"] is None
    # a layout whose router moves is told to move it, as before: the thing stands on the router's link there
    pin(monkeypatch, "strip")
    desk = [m["advice"] for m in state.run(fake.load_path("thing_left")) if m["type"] == "state" and m["advice"]]
    assert desk and all(a["to_spot"] in ("S-W30", "S-E30") for a in desk)


def test_somebody_on_the_spot_is_never_a_dead_zone_in_the_fake_brain(monkeypatch):
    lay = pin(monkeypatch, "spot")
    x, y = lay.centres[1]
    path = {"name": "both", "duration_s": 40, "person": [{"t": 0, "x": None}, {"t": 20, "x": x, "y": y}, {"t": 40, "x": x, "y": y}],
            "objects": [{"on": "line", "drop_db": 5.0, "t_on": 5}]}
    states = [m for m in state.run(lay.resolve(path)) if m["type"] == "state"]
    t0 = states[0]["t"]
    assert any(m["advice"] for m in states if m["t"] - t0 < 20)
    here = [m for m in states if m["t"] - t0 >= 20.2]
    assert all(m["advice"] is None and m["pred"]["kind"] == "person" for m in here)


def test_the_presence_line_drops_as_far_as_it_did_on_the_kit(monkeypatch):
    lay = pin(monkeypatch, "spot")
    events = list(fake.simulate({"name": "stand", "duration_s": 6, "person": [{"t": 0, "x": 0.4, "y": 0.3}]}, seed=1, noise_db=0.0))
    level = lambda link: sorted(e["dbm"] for e in events if e["type"] == "rssi" and e["link"] == link)[0]   # noqa: E731
    empty = {fake.link_id(tx, rx, kind): round(fake.baseline(tx, rx, kind)) for tx, rx, kind in lay.links}
    assert 15 <= empty["pi5>pi5b:wifi"] - level("pi5>pi5b:wifi") <= 21
    assert 6 <= empty["pi5b>unoq:ble"] - level("pi5b>unoq:ble") <= 9


# ---- the fake feed through the real brain (simulated: this shows the rules hold on the fake feed, not how the desk does) ----

def real_brain(monkeypatch, folder):
    """The real bus and brain on the one-spot layout, fed by the fake feed; None when the brain has no rules for a
    presence line's spread yet (they come with the brain's own change, and this file must pass without it)."""
    from functools import partial

    from brain.core import Brain
    from sim import rehearse
    if not hasattr(Brain, "_thing_says"):
        return None
    lay = pin(monkeypatch, "spot")
    doc = json.loads((LAYOUTS / "spot.json").read_text(encoding="utf-8"))
    for attr, value in {"LAYOUT": lay, "Z": lay.centres, "TOUR": lay.tour(), "STILL": lay.still_zone(), "CALM": lay.calm_zone(),
                        "TRAY": {"x": lay.tray[0], "y": lay.tray[1], "drop_db": 10}, "Brain": partial(Brain, nodes=doc)}.items():
        monkeypatch.setattr(rehearse, attr, value)
    return rehearse


def test_the_one_spot_rehearsal_passes_on_the_real_brain_with_a_thing_left_in_the_line(monkeypatch, tmp_path):
    import pytest
    rehearse = real_brain(monkeypatch, tmp_path)
    if rehearse is None:
        pytest.skip("the brain has no presence-line rules for a thing in the line yet")
    results = rehearse.rehearse(rehearse.spot_script())
    assert [name for name, passed, _ in results if not passed] == []
    assert any(name.startswith("thing taken away") for name, _, _ in results)


def test_moving_and_still_are_each_right_nine_times_in_ten_and_ten_empty_minutes_show_nothing(monkeypatch, tmp_path):
    import pytest
    rehearse = real_brain(monkeypatch, tmp_path)
    if rehearse is None:
        pytest.skip("the brain has no presence-line rules for moving and still yet")
    lay = rehearse.LAYOUT
    x, y = lay.centres[1]
    stack = rehearse.Stack(tmp_path, seed=5)
    assert "trained" in stack.calibrate()
    person, t = [{"t": 0, "x": None}, {"t": 3, "x": x, "y": y}], 4
    spans = []
    for i in range(6):                                # 20 s standing, 20 s stepping about, six times over
        person += [{"t": t, "x": x, "y": y}, {"t": t + 20, "x": x, "y": y}]
        spans.append(("still", t + 3, t + 20))
        person += rehearse.wander(1, t + 20, t + 40, step_s=0.6)
        spans.append(("moving", t + 23, t + 40))
        t += 40
    person += [{"t": t + 1, "x": None}]
    n = len(stack.states)
    t0 = stack.play({"name": "motion", "duration_s": t + 4, "person": person})
    said = {"still": [], "moving": []}
    for s in stack.states[n:]:
        at = (s["t"] - t0) / 1000
        for kind, a, b in spans:
            if a <= at < b and s["pred"] and s["pred"]["present"]:
                said[kind].append(s["pred"]["motion"])
    share = {kind: sum(m == kind for m in v) / len(v) for kind, v in said.items()}
    assert min(len(v) for v in said.values()) > 900 and share["moving"] >= 0.9 and share["still"] >= 0.9, share
    n, e = len(stack.states), len(stack.events)
    stack.play({"name": "empty", "duration_s": 600, "person": None})
    quiet = stack.states[n:]
    assert len(quiet) > 5000 and all(s["pred"] is not None and not s["pred"]["present"] and s["pred"]["kind"] == "none"
                                    and not s["advice"] and not s["objects"] and s["alert"]["state"] == "none" for s in quiet)
    assert [x["kind"] for x in stack.events[e:] if x["kind"] not in ("recording", "cam_off", "cam_on")] == []
