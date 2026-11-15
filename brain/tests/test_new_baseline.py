"""A model survives a new baseline of the same layout (issue #438), and says when it is not sure."""
import logging
import pickle

import numpy as np

from brain import features as F
from brain.core import Brain
from brain.tests.simdata import sim_to_v2
from brain.tests.test_core import Feed, cmd, record_to_disk, taught, taught_on_disk

SHIFT = {"pi5>unoq:wifi": -7, "pi5>unoq:ble": 4, "east>unoq:ble": -3, "west>unoq:ble": 6,
         "east>pi5:ble": -5, "west>pi5:ble": 2}          # another desk: every link sits at another level


def shifted(m):
    return dict(m, dbm=m["dbm"] + SHIFT[m["link"]]) if m["type"] == "rssi" else m


def zones_seen(brain, t0, path, seed, edit=None):
    out = []
    msgs = sim_to_v2(path, seed=seed, t0=t0)
    for m in msgs:
        brain.on_message(edit(m) if edit else m)
        if m["type"] == "label":
            out.append(brain.pred and (brain.pred["zone"], brain.pred["kind"], brain.pred["motion"]))
    return out, msgs[-1]["recv_t"] + 100


def test_the_same_model_gives_the_same_zones_after_every_level_shifts_and_a_new_baseline():
    brain, feed = taught()
    model = brain.model
    before, feed.t = zones_seen(brain, feed.t, "zone_tour", seed=80)

    brain.on_cmd(cmd("baseline", keep_model=True))        # the kit was carried to another desk
    for m in sim_to_v2("empty_room", seed=81, t0=feed.t):
        brain.on_message(shifted(m))
    feed.t = brain.feed_t + 100
    assert brain.capture is None and brain.model is model and brain.state()["model"]["trained"]
    assert abs(brain.base["pi5>unoq:wifi"] - model.base["pi5>unoq:wifi"] + 7) <= 1   # the baseline did move

    after, feed.t = zones_seen(brain, feed.t, "zone_tour", seed=80, edit=shifted)
    assert len(after) == len(before) and {z for z, _, _ in filter(None, after)} >= {1, 2, 3, 4}
    same = sum(a == b for a, b in zip(before[20:], after[20:]))
    assert same >= 0.97 * len(before[20:])                # the same walk reads the same; no retraining


def test_a_plain_baseline_still_means_a_new_place_and_keep_model_keeps_the_recordings(tmp_path):
    brain, feed = taught_on_disk(tmp_path)
    place = brain.place_t
    brain.on_cmd(cmd("baseline", keep_model=True))
    feed.play("empty_room", seed=60)
    assert brain.model is not None and brain.place_t == place and sorted(brain.sessions) == ["s01", "s02", "s10", "s11"]
    assert Brain(sessions_dir=tmp_path).model is not None           # and a restart keeps it too
    brain.on_cmd(cmd("baseline"))
    feed.play("empty_room", seed=61)
    assert brain.model is None and brain.sessions == {} and brain.place_t != place


def test_recordings_from_before_a_new_baseline_are_trained_against_their_own_baseline(tmp_path):
    brain = Brain(sessions_dir=tmp_path)
    feed = Feed(brain)
    brain.on_cmd(cmd("baseline"))
    feed.play("empty_room", seed=1)
    record_to_disk(brain, feed, tmp_path, "s01", "empty_room", seed=2)
    record_to_disk(brain, feed, tmp_path, "s10", "zone_tour", walker="w1", seed=10)
    first = dict(brain.base)
    brain.on_cmd(cmd("baseline", keep_model=True))                  # moved: levels shift, then one more walk
    for m in sim_to_v2("empty_room", seed=3, t0=feed.t):
        brain.on_message(shifted(m))
    feed.t = brain.feed_t + 100
    assert brain.base != first

    seen = {}
    real = brain.spawn

    def spawn(fit, done):
        model = fit()
        seen.update({s["meta"]["session"]: s["base"] for s in
                     next(c.cell_contents for c in fit.__closure__ if isinstance(c.cell_contents, list)
                          and c.cell_contents and isinstance(c.cell_contents[0], dict) and "meta" in c.cell_contents[0])})
        done(model)

    brain.spawn = spawn
    brain.on_cmd(cmd("train"))
    assert seen["s10"] == first and seen["s01"] == first            # not the new baseline
    again = Brain(sessions_dir=tmp_path)                            # and the same after a restart
    again.spawn = spawn
    seen.clear()
    again.on_cmd(cmd("train"))
    assert seen["s10"] == first


def test_a_model_file_trained_on_other_features_is_refused_and_says_why(tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger="brain")
    brain, _ = taught_on_disk(tmp_path)
    doc = pickle.loads((tmp_path / "model.pkl").read_bytes())
    doc["model"].features = ["pi5>unoq:wifi.mean"] + doc["model"].features[1:]    # yesterday's features, in dBm
    (tmp_path / "model.pkl").write_bytes(pickle.dumps(doc))
    again = Brain(sessions_dir=tmp_path)
    assert again.model is None and again.state()["pred"] is None
    assert any("other features" in r.getMessage() and "train again" in r.getMessage() for r in caplog.records)


def test_links_that_read_like_nothing_in_training_give_every_zone_not_one():
    brain, feed = taught()
    model = brain.model
    window = next(w for w in F.windows(sim_to_v2("stand_still", seed=31), model.base)
                  if w["label"] and w["label"]["present"])
    sure = model.predict(window)
    assert sure["present"] and len(sure["zone_set"]) == 1 and model.familiar(np.array(F.vector(window)))

    odd = dict(window, links={k: dict(v, mean=v["mean"] - (25 if k == "west>pi5:ble" else 0))
                              for k, v in window["links"].items()})   # one link 25 dB deeper than anything taught
    assert not model.familiar(np.array(F.vector(odd)))
    unsure = model.predict(odd)
    if unsure["present"]:
        assert unsure["zone_set"] == [1, 2, 3, 4]                   # "somebody, not sure where"
    assert unsure["zone"] in (0, 1, 2, 3, 4) and len(unsure["probs"]) == 5


def test_keep_model_baseline_runs_with_the_camera_unplugged_and_keeps_the_model():
    brain, feed = taught()
    model = brain.model

    def no_camera(m):
        return None if m["type"] in ("cam", "label") else shifted(m)

    def play(seed):
        for m in sim_to_v2("empty_room", seed=seed, t0=feed.t):
            m = no_camera(m)
            if m:
                brain.on_message(m)
        feed.t = brain.feed_t + 100

    play(84)                                           # the camera has been unplugged for a while
    brain.on_cmd(cmd("baseline", keep_model=True))
    play(85)
    assert brain.capture is None and brain.model is model          # done, with nobody watching
    brain.on_cmd(cmd("baseline"))                      # a plain baseline also runs, and is a new place
    play(86)
    assert brain.capture is None and brain.model is None


def lossy_capture(brain, t0, seconds, drop, seed=70):
    """Empty-room readings with some dropped (drop(link, ms into the feed) -> True), state taken as the
    live loop does. Returns (seconds until baseline_done or None, the time after the feed)."""
    done, t = None, t0
    brain.pop_events()
    while t - t0 < seconds * 1000:
        for m in sim_to_v2("empty_room", seed=seed, t0=t):
            if m["type"] == "rssi" and drop(m["link"], m["recv_t"] - t0):
                continue
            brain.on_message(m)
            if m["type"] == "label":
                brain.state()
            if done is None and any(e["kind"] == "baseline_done" for e in brain.pop_events()):
                done = (m["recv_t"] - t0) / 1000
            t = m["recv_t"] + 100
    return done, t


def bursts(link, ms):
    """30% of the readings lost, in 1.5 s gaps: each link drops out for 1.5 s in every 5, at its own time."""
    return (ms + 700 * sorted(SHIFT).index(link)) % 5000 < 1500


def test_a_keep_model_baseline_finishes_with_30_percent_of_the_readings_lost_in_bursts():
    brain, feed = taught()
    model = brain.model
    brain.on_cmd(cmd("baseline", keep_model=True))        # the same kit at the judging desk, in a hall full of phones
    done, feed.t = lossy_capture(brain, feed.t, 60, bursts)
    assert done is not None and done <= 25 and brain.model is model       # stale links don't hold it up
    assert all(abs(brain.base[k] - model.base[k]) <= 1.5 for k in brain.base)   # and the baseline is a sound one

    brain.on_cmd(cmd("baseline"))                         # a new place waits for the same things now (#634)
    done, feed.t = lossy_capture(brain, feed.t, 60, bursts)
    assert done is not None and done <= 25 and brain.capture is None
    assert brain.model is None                            # and it is still a new place: the old model is dropped


def test_a_keep_model_baseline_still_restarts_for_a_link_silent_3_s():
    brain, feed = taught()
    brain.on_cmd(cmd("baseline", keep_model=True))
    unplugged = lambda link, ms: link == "east>unoq:ble" and 5000 <= ms < 9500   # noqa: E731
    done, feed.t = lossy_capture(brain, feed.t, 60, unplugged)
    assert done is not None and 28 <= done <= 36          # the 20 s started again once the link was back
