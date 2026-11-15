"""A baseline asked for by hand that can never start doesn't hide pred for ever."""
import logging

from brain.core import BASELINE_GIVE_UP_MS
from brain.tests.test_core import cmd, taught


def somebody_in_frame(m):
    return dict(m, persons_in_frame=1) if m["type"] == "label" else m


def play(brain, feed, path, seed, edit=None, each=None):
    from brain.tests.simdata import sim_to_v2
    msgs = sim_to_v2(path, seed=seed, t0=feed.t)
    for m in msgs:
        brain.on_message(edit(m) if edit else m)
        if each:
            each(m)
    feed.t = msgs[-1]["recv_t"] + 100


def test_baseline_pressed_by_mistake_in_front_of_people_gives_up_and_pred_comes_back(caplog):
    caplog.set_level(logging.WARNING, logger="brain")
    brain, feed = taught()
    model, base, place = brain.model, dict(brain.base), brain.place_t
    brain.pop_events()
    brain.on_cmd(cmd("baseline"))                       # a slip of the finger; the camera sees the judges
    t0, log = feed.t, []                                # (seconds since the press, waiting?, pred zone or None)
    for seed in range(70, 76):
        play(brain, feed, "zone_tour", seed, edit=somebody_in_frame,
             each=lambda m: log.append(((m["recv_t"] - t0) / 1000, brain.capture is not None,
                                        brain.pred["zone"] if brain.pred else None)))
    give_up_s = BASELINE_GIVE_UP_MS / 1000
    assert all(waiting and zone is None for s, waiting, zone in log if 1 < s < give_up_s - 1)   # hidden meanwhile
    after = [(waiting, zone) for s, waiting, zone in log if s > give_up_s + 3]
    assert after and not any(waiting for waiting, _ in after)                    # given up
    assert {1, 2, 3, 4} <= {zone for _, zone in after}                           # and pred is back
    assert brain.model is model and brain.base == base and brain.place_t == place   # nothing was dropped
    assert "baseline_done" not in [e["kind"] for e in brain.events]
    said = [r.getMessage() for r in caplog.records if "given up" in r.getMessage()]
    assert len(said) == 1 and "the camera sees somebody" in said[0]


def test_a_baseline_that_is_capturing_when_the_time_runs_out_is_allowed_to_finish():
    brain, feed = taught()
    brain.on_cmd(cmd("baseline"))
    t0 = feed.t
    clear_at = t0 + BASELINE_GIVE_UP_MS - 8_000         # the room clears only just before the limit

    def edit(m):
        return somebody_in_frame(m) if m["recv_t"] < clear_at else m

    brain.pop_events()
    for seed in range(72, 78):                          # 180 s: the 20 s capture runs across the limit
        play(brain, feed, "empty_room", seed, edit=edit)
    assert brain.capture is None and "baseline_done" in [e["kind"] for e in brain.pop_events()]


def test_a_keep_model_baseline_that_cannot_start_is_given_up_too(caplog):
    caplog.set_level(logging.WARNING, logger="brain")
    brain, feed = taught()
    model, base = brain.model, dict(brain.base)
    brain.pop_events()
    brain.on_cmd(cmd("baseline", keep_model=True))      # the camera is on and sees the judges
    t0, log = feed.t, []
    for seed in range(80, 86):
        play(brain, feed, "zone_tour", seed, edit=somebody_in_frame,
             each=lambda m: log.append(((m["recv_t"] - t0) / 1000, brain.capture is not None, brain.pred is not None)))
    give_up_s = BASELINE_GIVE_UP_MS / 1000
    assert all(waiting for s, waiting, _ in log if 1 < s < give_up_s - 1)
    after = [(waiting, shown) for s, waiting, shown in log if s > give_up_s + 3]
    assert after and not any(waiting for waiting, _ in after) and any(shown for _, shown in after)
    assert brain.model is model and brain.base == base
    assert sum("given up" in r.getMessage() for r in caplog.records) == 1
