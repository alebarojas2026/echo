"""lab/gate_tune.py, gate_lines.py and gate_pick.py on made-up session files.

The files here are invented (a steady Wi-Fi line that falls 18 dB with somebody on the spot).
They show the tools do what they say; they say nothing about the real kit.
"""
import json
import random

import pytest

from lab import gate_lines, gate_pick, gate_tune

from brain.core import Brain

# The replay needs a brain that reads the layout's presence line (the one-spot brain, #776).
pytestmark = pytest.mark.skipif(not hasattr(Brain, "_line_says"),
                                reason="this brain has no presence line yet: the one-spot rules are not merged")

WIFI, BLE, BLE2 = "pi5>pi5b:wifi", "pi5b>unoq:ble", "pi5b>pi5:ble"
T0 = 1_700_000_000_000


def write(folder, name, plan, seed=0, t0=T0):
    """plan: [(seconds, fall in dB on the Wi-Fi line)]. Writes a session file as the bus does."""
    rng, t, rows = random.Random(seed), t0, []
    rows.append({"v": 2, "type": "meta", "t": t, "recv_t": t, "session": name, "purpose": "demo"})
    for seconds, fall in plan:
        for i in range(int(seconds * 25)):
            at = t + i * 40
            rows.append({"v": 2, "type": "rssi", "t": at, "recv_t": at, "link": WIFI, "dbm": -40 - fall + rng.choice((-1, 0, 0, 0, 1))})
            if i % 5 == 0:
                rows.append({"v": 2, "type": "rssi", "t": at, "recv_t": at + 1, "link": BLE, "dbm": -58 - fall / 3 + rng.randint(-3, 3)})
            if i % 8 == 0:
                rows.append({"v": 2, "type": "rssi", "t": at, "recv_t": at + 2, "link": BLE2, "dbm": -65 + rng.randint(-3, 3)})
        t += int(seconds * 1000)
    (folder / f"{name}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


@pytest.fixture(scope="module")
def kit(tmp_path_factory):
    folder = tmp_path_factory.mktemp("sessions")
    write(folder, "base", [(10, 0)], 1)
    write(folder, "p1", [(8, 18)], 2)
    write(folder, "e1", [(8, 0)], 3)
    write(folder, "walk", [(5, 0), (1, 18), (5, 0), (1, 18), (5, 0)], 4)
    write(folder, "still", [(8, 18)], 5)
    write(folder, "held-p", [(8, 18)], 6)
    write(folder, "held-e", [(8, 0)], 7)
    plan = {"runs": [{"id": "r", "layout": "gate-3", "sessions": [
        {"session": "base", "is": "baseline", "set": "tune"},
        {"session": "p1", "is": "person", "set": "tune"},
        {"session": "e1", "is": "empty", "set": "tune"},
        {"session": "held-p", "is": "person", "set": "heldout"},
        {"session": "held-e", "is": "empty", "set": "heldout"},
        {"session": "walk", "is": "walk", "set": "tune", "passes": 2},
        {"session": "still", "is": "still", "set": "tune"}]}]}
    return folder, plan


def test_tuning_never_opens_a_held_out_file(kit, monkeypatch):
    folder, plan = kit
    opened = []
    real = gate_tune.read_rssi
    monkeypatch.setattr(gate_tune, "read_rssi", lambda path: opened.append(path.stem) or real(path))
    runs = gate_tune.load(folder, plan, "tune")
    assert opened == ["base", "p1", "e1", "walk", "still"]
    assert [p["session"] for p in runs[0]["parts"]] == opened
    # the sessions either side of the held-out ones are joined end to end
    parts = runs[0]["parts"]
    assert all(b["start"] - a["end"] == 0 for a, b in zip(parts, parts[1:]))


def test_the_held_out_replay_plays_the_evening_and_scores_only_the_held_out_sessions(kit):
    folder, plan = kit
    runs = gate_tune.load(folder, plan, "heldout")
    assert [p["session"] for p in runs[0]["parts"] if p["scored"]] == ["held-p", "held-e"]
    assert len(runs[0]["parts"]) == 7
    got = gate_tune.run_variant(runs, detail=True)
    assert [r["session"] for r in got["sessions"]] == ["held-p", "held-e"]


def test_a_run_whose_baseline_is_held_out_cannot_be_tuned_on(kit):
    folder, plan = kit
    bad = {"runs": [{"id": "x", "sessions": [{"session": "base", "is": "baseline", "set": "heldout"},
                                             {"session": "p1", "is": "person", "set": "tune"}]}]}
    with pytest.raises(ValueError, match="held-out"):
        gate_tune.load(folder, bad, "tune")
    all_held = {"runs": [{"id": "x", "sessions": [{"session": "base", "is": "baseline", "set": "heldout"},
                                                  {"session": "held-p", "is": "person", "set": "heldout"}]}]}
    assert gate_tune.load(folder, all_held, "tune") == []          # nothing to tune on: left out whole
    assert len(gate_tune.load(folder, all_held, "heldout")) == 1


def test_the_brain_finds_the_person_lets_go_and_calls_a_walk_through_passed_by(kit):
    folder, plan = kit
    got = gate_tune.run_variant(gate_tune.load(folder, plan, "tune"), detail=True)
    total = got["total"]
    assert total["people"] == total["found"] == 2 and total["not_found"] == 0
    assert total["false_present_s"] == 0 and total["false_enters"] == 0 and total["not_released"] == 0
    assert 0.2 < total["detect_s"] < 1.0 and 0.2 < total["release_s"] < 1.0   # half the 1 s median, at a join
    walk = total["walk"]
    assert walk["passes"] == walk["on_line"] == walk["seen"] == 2
    assert walk["armed"]["3.0"] == {"passed_by": 2, "intrusion": 0}
    assert gate_pick.safe(total, 3.0)
    by = {r["session"]: r for r in got["sessions"]}
    assert by["still"]["motion_right"] > 0.9 * by["still"]["motion_n"]


def test_the_layout_numbers_are_what_decides(kit):
    folder, plan = kit
    runs = gate_tune.load(folder, plan, "tune")
    deaf = gate_tune.run_variant(runs, {"on_db": 25.0, "off_db": 20.0})["total"]
    assert deaf["found"] == 0 and not gate_pick.safe(deaf, 3.0)
    long_ = gate_tune.run_variant(runs, {"window_ms": 2000})["total"]
    assert long_["walk"]["seen"] < 2 or long_["detect_s"] > 0.9   # a 2 s median needs over a second in the line
    with pytest.raises(ValueError, match="not something a variant can change"):
        gate_tune.run_variant(runs, {"on": 7})


def test_the_window_lengths_are_put_back_after_a_replay(kit):
    from brain import features as F
    folder, plan = kit
    gate_tune.run_variant(gate_tune.load(folder, plan, "tune"), {"window_ms": 500, "spread_ms": 3000})
    assert (F.WINDOW_MS, F.STEADY_MS) == (1000, 2000)


def test_the_line_table(kit):
    folder, plan = kit
    table = gate_lines.from_plan(folder, plan, "tune")["r"]
    wifi = table[WIFI]
    assert wifi["per_s"] == pytest.approx(25, abs=0.5) and wifi["quiet_dbm"] == -40 and wifi["rounds"] == 2
    assert wifi["person"][0] == pytest.approx(18, abs=1) and wifi["empty_dip"] <= 1 and wifi["gap"] >= 16
    assert "walk (walk)" in wifi["checks"] and wifi["checks"]["walk (walk)"]["deepest_half_second"] >= 17
    assert "| r | `pi5>pi5b:wifi` |" in gate_lines.markdown({"r": table})


def row(on, off, **total):
    base = {"false_present_s": 0, "false_enters": 0, "false_alarms": {"3.0": 0}, "people": 2, "found": 2,
            "not_found": 0, "not_released": 0, "dropouts_standing": 0, "detect_s": on / 10, "release_s": 0.5}
    return {"params": {**gate_tune.DEFAULTS, "on_db": on, "off_db": off}, "total": {**base, **total}}


def test_the_pick_is_the_middle_of_the_safe_region_not_its_fastest_edge():
    rows = []
    for on in (4, 5, 6, 7, 8, 9, 10):
        for off in (2, 3, 4):
            if off < on:
                rows.append(row(on, off, **({"false_present_s": 1.5} if on == 4 else {"found": 1} if on == 10 else {})))
    got = gate_pick.study(rows, 3.0)
    assert got["variants"] == 20 and got["safe"] == 15
    assert got["pick"]["params"]["on_db"] == 7 and got["pick"]["room_steps"] == 2    # two steps from either cliff
    assert got["fastest_safe"]["params"]["on_db"] == 5 and got["fastest_safe"]["room_steps"] == 0
    assert got["span_at_pick"]["on_db"]["safe"] == [5, 6, 7, 8, 9]
    assert gate_pick.study([row(4, 2, false_enters=1)], 3.0)["pick"] is None


def test_the_sweep_only_makes_variants_that_can_run():
    pytest.importorskip("modal")
    from lab import gate_sweep
    made = gate_sweep.variants("presence", {})
    assert made and all(v["off_db"] < v["on_db"] for v in made)
    assert all(set(v) <= set(gate_tune.DEFAULTS) for v in made + gate_sweep.variants("motion", {"on_db": 8}))
