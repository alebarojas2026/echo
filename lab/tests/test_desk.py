"""The desk strip: layout, scene and the replayed rules (SIMULATED data)."""
import numpy as np

from lab import desk, rf


def test_layout_is_the_strip_and_the_arms_move():
    doc = desk.desk_doc(0.35)
    lay = desk.Lay(doc)
    assert len(lay.links) == 12 and len(lay.nodes) == 5
    assert lay.nodes["west"] == (0.0, 0.25) and lay.nodes["east"] == (1.6, 0.25)
    assert desk.Lay(desk.desk_doc(0.45)).tip_y == 0.15
    assert set(desk.CROSS) <= set(lay.links) and set(desk.SIX) <= set(lay.links)


def test_scene_has_every_part_and_passers_keep_off_the_desk():
    S, plan = desk.build(3, rf.Env(), {"rate": 8})
    for part in ("desk_baseline", "arrival", "short", "up", "left", "still", "fidget", "armed_empty",
                 "intruder", "through", "brush"):
        assert S.spans.get(part), part
    cmds = [c for _, c, _ in S.cmds]
    assert cmds[0] == "baseline" and "train" in cmds and cmds.count("arm") == 2
    passers = [b for b in S.bodies if b.tag.startswith("passer")]
    assert 15 <= len(passers) <= 60
    assert all(b.t0 >= plan["tB"] - 8 for b in passers)
    assert max(float(b.y.max()) for b in passers) < plan["tip_y"] + 0.1     # nobody walks through the arms
    judge = next(b for b in S.bodies if b.tag == "visit1")
    a, c = S.spans["still"][0]
    x, y = judge.at(np.array([a + 1.0, c - 1.0]))
    assert abs(x[0] - x[1]) < 0.1 and 0.3 < y[0] < 0.6                     # still, and up at the desk


def test_a_body_on_a_strip_link_drops_it_and_one_in_the_aisle_does_not():
    lay = desk.Lay(desk.desk_doc())
    a, b = lay.nodes["east"], lay.nodes["unoq"]
    on = rf.shadow_db(np.array([1.35]), np.array([0.42]), a, b, rf.LAMBDA_M["ble"], 0.4, 8.0, 1.75)[0]
    off = rf.shadow_db(np.array([1.35]), np.array([-0.15]), a, b, rf.LAMBDA_M["ble"], 0.4, 8.0, 1.75)[0]
    assert on > 6.0 and abs(off) < 0.5


def _log(spec):
    """spec: [(n decisions, present, motion)] -> a decision log at 10 a second."""
    out, t = [], 1_000_000
    for n, present, motion in spec:
        for _ in range(n):
            t += 100
            out.append((t, (present, "person" if present else "none", 2 if present else 0,
                            motion if present else None, 1, [0.0] * 12, [0.0] * 12)))
    return out


def test_armed_wait_turns_a_passer_into_passed_by():
    log = _log([(30, False, None), (15, True, "moving"), (30, False, None), (60, True, "still"), (20, False, None)])
    today = desk.replay_armed(log)
    assert [k for _, k, _ in today] == ["intrusion", "intrusion"]
    wait = desk.replay_armed(log, confirm_s=2.0)
    assert [k for _, k, _ in wait] == ["passed_by", "intrusion"]
    assert wait[1][2] == 2
    assert wait[1][0] - today[1][0] == 2000


def test_still_timer_reset_and_pause():
    limits = {1: 10, 2: 10}
    # 6 s still, 0.8 s of "moving" (somebody walks past), 6 s still
    log = _log([(60, True, "still"), (8, True, "moving"), (60, True, "still")])
    assert desk.replay_still(log, limits) == []                              # today: the blip resets it
    assert len(desk.replay_still(log, limits, run_n=10)) == 1
    assert len(desk.replay_still(log, limits, mode="pause")) == 1
    # real walking for 4 s clears a paused timer too
    log = _log([(60, True, "still"), (40, True, "moving"), (60, True, "still")])
    assert desk.replay_still(log, limits, mode="pause", pause_reset_n=30) == []


def test_found_needs_a_run_and_a_hold():
    log = _log([(20, False, None), (2, True, "still"), (20, False, None), (50, True, "still")])
    shown, opened = desk.replay_found(log, show_n=1, hold_s=3.0)
    assert len(shown) == 2 and len(opened) == 1
    shown, opened = desk.replay_found(log, show_n=5, hold_s=3.0)
    assert len(shown) == 1 and len(opened) == 1


def test_one_session_runs_through_the_brain_and_the_replay_matches_it():
    out = desk.session(seed=5, scene={"rate": 6}, keep_log=True)
    m = out["metrics"]
    assert m["trained"] and m["decisions"] > 500
    assert set(m["armed"]) >= {"0.0/10/6", "2.0/10/6"} and len(m["still"]) == len(desk.STILL_GRID)
    # The replayed rules with today's settings give back the brain's own events.
    S, log = out["_scene"], out["_log"]
    sec = lambda ms: (ms - rf.T0_MS) / 1000.0   # noqa: E731
    arm_on, arm_off = (t for t, c, _ in S.cmds if c == "arm")
    mine = [sec(t) for t, k, _ in desk.replay_armed([(t, d) for t, d in log if arm_on <= sec(t) < arm_off])
            if k == "intrusion"]
    brain = [sec(t) for t, k, _ in out["_events"] if k == "intrusion"]
    assert len(mine) == len(brain) and all(abs(a - b) <= 0.2 for a, b in zip(mine, brain))
    limits = {1: 10, 2: 10}
    resets = [rf.T0_MS + t * 1000 for t, c, _ in S.cmds if c == "reset"]
    mine = [sec(t) for t, _ in desk.replay_still(log, limits, resets)]
    brain = [sec(t) for t, k, _ in out["_events"] if k == "alert_on"]
    assert len(mine) == len(brain) and all(abs(a - b) <= 0.2 for a, b in zip(mine, brain))
