"""The automatic baseline with the camera unplugged is not taken over a stretch with somebody walking in it (#518)."""
import json

from brain.tests.simdata import sim_to_v2
from brain.tests.test_core import cmd, taught


def play(brain, feed, name, seed, at=None, path=None):
    """Play a path with commands at given seconds. Returns [(seconds from the start of this path, event kind)]."""
    msgs, todo, seen = sim_to_v2(path or name, seed=seed, t0=feed.t), dict(at or {}), []
    t0 = msgs[0]["recv_t"]
    for m in msgs:
        for s in sorted(todo):
            if m["recv_t"] - t0 >= s * 1000:
                brain.on_cmd(todo.pop(s))
        brain.on_message(m)
        if m["type"] == "cam" or m["recv_t"] % 200 < 70:
            brain.state()
        seen += [((m["recv_t"] - t0) / 1000, e["kind"]) for e in brain.pop_events()
                 if e["kind"] in ("router_home", "recalibrating", "baseline_done")]
    feed.t = msgs[-1]["recv_t"] + 100
    return seen


def test_the_baseline_after_router_home_waits_until_nobody_walks_in_it():
    """camera_unplug: the camera goes off at 14 s and somebody walks about until 28 s. The router
    comes home at 12 s with them next to its links, so the 3 s check fails and a baseline starts."""
    brain, feed = taught()
    brain.pop_events()
    old = dict(brain.base)
    first = play(brain, feed, "camera_unplug", 7,
                 at={2: cmd("router_moved", spot="S-W30"), 12: cmd("router_home")})
    assert [k for _, k in first] == ["router_home", "recalibrating"]        # nothing finishes with them in it
    second = play(brain, feed, "empty_room", 8)                             # 30 s of an empty square
    third = play(brain, feed, "empty_room", 9)
    done = [(i, s) for i, part in enumerate((second, third)) for s, k in part if k == "baseline_done"]
    assert len(done) == 1
    part, s = done[0]
    empty_for = 32 - 28.1 + part * 30 + s                                   # the square has been empty since 28.1 s
    assert empty_for >= 20, done
    assert all(abs(brain.base[k] - old[k]) <= 1.0 for k in old)             # so the new baseline is an empty room's
    assert brain.state()["pred"] is not None and not brain.recalibrating


def camera_off_path(tmp_path, person):
    file = tmp_path / "walk.json"
    file.write_text(json.dumps({"name": "walk", "duration_s": 32, "camera": [{"t": 0, "state": "off"}],
                                "person": [{"t": 0, "x": None}] + person}))
    return str(file)


def automatic(brain):
    """Put the brain where a failed router_home check leaves it: an automatic baseline running."""
    brain.recalibrating = True
    brain._start_capture(new_place=False, by_hand=False)


def test_somebody_passing_for_a_moment_does_not_hold_the_baseline_up(tmp_path):
    brain, feed = taught()
    brain.pop_events()
    passer = [{"t": 8, "x": 0.0, "y": 0.5}, {"t": 10, "x": 2.0, "y": 0.5}, {"t": 10.1, "x": None}]
    automatic(brain)
    seen = play(brain, feed, "walk", 3, path=camera_off_path(tmp_path, passer))
    done = [s for s, k in seen if k == "baseline_done"]
    assert len(done) == 1 and done[0] <= 23                                 # 2 s of a passer-by in the 20: used


def test_whatever_is_used_is_an_empty_rooms_baseline(tmp_path):
    """Somebody on the move through all four zones for 10 of the 20 s shadows each link for a few
    seconds only. Each link's median holds, so the capture may be used; what must never happen is
    a baseline that sits away from the empty room's."""
    brain, feed = taught()
    brain.pop_events()
    old = dict(brain.base)
    walker = [{"t": 2 + 2 * i, "x": (0.5, 1.5)[i % 2], "y": (0.5, 1.5)[i // 2 % 2]} for i in range(6)] + [{"t": 12.1, "x": None}]
    automatic(brain)
    seen = play(brain, feed, "walk", 3, path=camera_off_path(tmp_path, walker))
    seen += play(brain, feed, "empty_room", 4)
    assert [k for _, k in seen] == ["baseline_done"]
    assert all(abs(brain.base[k] - old[k]) <= 1.0 for k in old)


def test_a_baseline_asked_for_by_hand_is_not_judged_this_way(tmp_path):
    brain, feed = taught()
    brain.pop_events()
    walker = [{"t": 2 + 2 * i, "x": (0.5, 1.5)[i % 2], "y": (0.5, 1.5)[i // 2 % 2]} for i in range(6)] + [{"t": 12.1, "x": None}]
    brain.on_cmd(cmd("baseline", keep_model=True))                          # the operator answers for the area
    seen = play(brain, feed, "walk", 3, path=camera_off_path(tmp_path, walker))
    done = [s for s, k in seen if k == "baseline_done"]
    assert len(done) == 1 and done[0] <= 23
