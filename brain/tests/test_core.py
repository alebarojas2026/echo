import pytest

from brain import features as F
from brain.core import Brain
from brain.tests.simdata import T0_MS, sim_to_v2

STATE_KEYS = {"v", "type", "t", "seq", "src", "cam", "router", "links", "health", "pred", "objects", "xray",
              "alert", "checkin", "advice", "narration", "teacher", "model", "board"}


def cmd(name, **args):
    return {"v": 2, "type": "cmd", "cmd": name, "args": args}


class Feed:
    """Plays sim paths into a brain one after another, on one growing clock."""

    def __init__(self, brain):
        self.brain, self.t = brain, T0_MS

    def play(self, path, seed=0, meta=None, mode=None, each=None, states=None, noise_db=1.0):
        """states: a list that collects (seconds into the path, state), one every 0.1 s like the live loop."""
        msgs = sim_to_v2(path, seed=seed, mode=mode, meta=meta, t0=self.t, noise_db=noise_db)
        last = 0
        for m in msgs:
            self.brain.on_message(m)
            if each:
                each(m)
            if states is not None and m["recv_t"] - last >= 100:
                last = m["recv_t"]
                states.append(((last - self.t) / 1000, self.brain.state()))
        self.t = msgs[-1]["recv_t"] + 100

    def record(self, session, path, purpose="train", walker=None, **kw):
        self.brain.on_cmd(cmd("record_start", session=session, purpose=purpose, walker=walker))
        self.play(path, meta={"session": session, "purpose": purpose, "walker": walker}, **kw)
        self.brain.on_cmd(cmd("record_stop"))


def taught(to_bus=None, **kw):
    """A brain with a baseline and a model trained on sim sessions."""
    brain = Brain(to_bus=to_bus, **kw)
    feed = Feed(brain)
    brain.on_cmd(cmd("baseline"))
    feed.play("empty_room", seed=1)
    feed.record("s01", "empty_room", seed=2)
    feed.record("s02", "metal_object", purpose="object", seed=3)
    feed.record("s03", "tray_t1", purpose="object", mode="object", seed=4)   # the tray, taught at T1
    for i, w in enumerate(["w1", "w2", "w3"]):
        feed.record(f"s1{i}", "zone_tour", walker=w, seed=10 + i)
        feed.record(f"s3{i}", "stand_still", walker=w, seed=30 + i)
    feed.record("s20", "zone_tour", purpose="heldout", walker="w4", seed=20)
    brain.on_cmd(cmd("train"))
    return brain, feed


@pytest.fixture(scope="module")
def ready():
    return taught()


def test_state_before_anything_has_the_contract_shape_and_no_pred():
    s = Brain().state()
    assert set(s) == STATE_KEYS and s["v"] == 2 and s["type"] == "state"
    assert s["pred"] is None and s["model"]["trained"] is False and s["cam"] == "off"
    # Section 5: what state looks like before readings, a baseline and training.
    assert s["links"] == [] and s["xray"] is None and s["objects"] == []
    assert s["health"] == {"status": "ok", "blind": [], "reason": None}
    assert s["alert"] == {"state": "none", "zone": None, "still_s": 0, "limit_s": None}
    assert s["advice"] is None and s["checkin"] is None and s["narration"] is None
    assert s["model"] == {"trained": False, "ver": None, "train_s": None, "ms_per_decision": None,
                          "windows": 0, "train_sessions": [], "training": None}
    assert set(s["board"]) == {"cpu_temp_c", "cpu_mhz", "cpu_pct"}

def test_baseline_takes_20_s_and_sets_base_and_expected_rate():
    brain = Brain()
    feed = Feed(brain)
    brain.on_cmd(cmd("baseline"))
    done_at = []
    feed.play("empty_room", each=lambda m: done_at.append(m["recv_t"]) if brain.base and not done_at else None)
    assert 20_000 <= done_at[0] - T0_MS < 20_200
    assert set(brain.base) == set(F.LINKS)
    assert all(14 <= hz <= 16 for hz in brain.expected_hz.values())
    s = brain.state()
    assert [l["id"] for l in s["links"]] == list(F.LINKS)
    assert len(s["xray"]["moving_db"]) == s["xray"]["w"] * s["xray"]["h"]
    assert [e["kind"] for e in brain.pop_events()] == ["baseline_done"]
    assert brain.label_mode == "off"


def test_someone_in_frame_restarts_the_baseline():
    brain = Brain()
    feed = Feed(brain)
    brain.on_cmd(cmd("baseline"))
    feed.play("zone_tour")       # 34 s with a person in frame for the first 30
    assert not brain.base
    feed.play("empty_room")
    assert set(brain.base) == set(F.LINKS)


def test_train_uses_train_and_object_sessions_only(ready):
    brain, _ = ready
    info = brain.state()["model"]
    assert info["trained"] and info["ver"] == "m1" and info["train_s"] is not None
    assert info["train_sessions"] == ["s01", "s02", "s03", "s10", "s11", "s12", "s30", "s31", "s32"]  # not held-out s20
    assert "trained" in [e["kind"] for e in brain.events]


def test_train_without_baseline_or_sessions_does_nothing():
    brain = Brain()
    brain.on_cmd(cmd("train"))
    assert brain.model is None and brain.training is None


def test_predictions_follow_the_walker(ready):
    brain, feed = ready
    hits = total = 0

    def check(m):
        nonlocal hits, total
        if m["type"] == "label" and brain.pred is not None:
            total += 1
            hits += int((brain.pred["zone"] or 0) == m["zone"])

    feed.play("zone_tour", seed=77, each=check)
    assert total > 100 and hits / total > 0.6
    s = brain.state()
    assert set(s) == STATE_KEYS and s["src"] == "sim" and s["cam"] == "on"
    assert s["model"]["ms_per_decision"] > 0
    assert s["teacher"] == {"present": False, "zone": 0, "motion": None}
    link = s["links"][0]
    assert set(link) == {"id", "dbm", "base_dbm", "drop_db", "rate_hz", "expected_hz", "status", "why"}
    assert link["status"] == "ok" and 0 <= link["why"] <= 1


def test_still_s_counts_while_standing(ready):
    brain, feed = ready
    seen = []
    feed.play("stand_still", seed=5, each=lambda m: seen.append(brain.pred["still_s"]) if brain.pred else None)
    assert max(seen) > 5
    brain.on_cmd(cmd("reset_alert"))
    assert brain._still_since is None


def test_router_off_home_means_no_pred(ready):
    brain, feed = ready
    brain.on_cmd(cmd("router_moved", spot="S-W30"))
    feed.play("zone_tour", seed=6)
    s = brain.state()
    assert s["router"] == "S-W30" and s["pred"] is None
    brain.on_cmd(cmd("router_home"))
    feed.play("zone_tour", seed=7)
    assert brain.state()["router"] == "S-home" and brain.pred is not None
    kinds = [e["kind"] for e in brain.pop_events()]
    assert "router_moved" in kinds and "router_home" in kinds


def test_commands_go_to_the_bus_and_label_mode_reaches_the_teacher(tmp_path):
    sent = []
    brain = Brain(to_bus=sent.append, mode_file=tmp_path / "label_mode")
    brain.on_cmd(cmd("label_mode", mode="object"))
    brain.on_cmd(cmd("label_mode", mode="selfie"))   # not a mode: ignored by the brain
    brain.on_cmd(cmd("record_start", session="s9", purpose="train", walker="w1"))
    brain.on_cmd(cmd("truth", zone=3))
    brain.on_cmd(cmd("made_up"))
    assert (tmp_path / "label_mode").read_text() == "object\n" and brain.label_mode == "object"
    assert [m["cmd"] for m in sent] == ["label_mode", "label_mode", "record_start", "truth"]
    assert brain.pop_events()[0]["info"] == {"on": True, "session": "s9"}
    assert sent[2]["args"] == {"session": "s9", "purpose": "train", "walker": "w1"}
    assert all(m["v"] == 2 and m["type"] == "cmd" for m in sent)
    assert [m["seq"] for m in sent] == [1, 2, 3, 4] and brain.truth == 3


def test_relearn_trains_a_new_version():
    brain, _ = taught()
    brain.on_cmd(cmd("relearn"))
    assert brain.state()["model"]["ver"] == "m2"


def test_links_go_stale_when_the_feed_stops():
    clock = [T0_MS]
    brain = Brain(clock=lambda: clock[0])
    brain.on_cmd(cmd("baseline"))
    for m in sim_to_v2("empty_room"):
        clock[0] = m["recv_t"]
        brain.on_message(m)
    assert all(l["status"] == "ok" for l in brain.state()["links"])
    clock[0] += 5_000
    s = brain.state()
    assert all(l["status"] == "stale" and l["rate_hz"] == 0 for l in s["links"]) and s["cam"] == "off"


def test_reset_clears_the_judge_state_and_recording_events_share_one_seq():
    brain = Brain()
    brain.on_message({"type": "narration", "recv_t": T0_MS, "text": "hi", "event_id": "e1", "t": T0_MS,
                      "source": "template", "gen_ms": 1})
    assert brain.state()["narration"]["text"] == "hi"
    brain.on_cmd(cmd("reset"))
    brain.on_cmd(cmd("record_stop"))
    after = brain.state()
    events = brain.pop_events()
    assert after["narration"] is None
    assert [(e["kind"], e["info"]) for e in events] == [("reset", {}), ("recording", {"on": False, "session": None})]
    assert [e["id"] for e in events] == ["e1", "e2"]
    # state, event, event, state: one counter across both types
    assert [events[0]["seq"], events[1]["seq"], after["seq"]] == [2, 3, 4]


def at(states, seconds):
    return next(s for t, s in states if t >= seconds)


def kinds(brain):
    return [e["kind"] for e in brain.pop_events()]


def test_a_dropped_link_means_sensor_blind_and_no_pred():
    brain, feed = taught()
    brain.pop_events()
    states = []
    feed.play("dropped_link", seed=3, states=states)   # the east beacon is silent from 10 to 20 s
    assert at(states, 8)["health"]["status"] == "ok" and at(states, 8)["pred"]["present"]
    blind = at(states, 16)
    assert blind["health"]["status"] == "blind" and blind["health"]["reason"] == "rate"
    assert set(blind["health"]["blind"]) == {"east>unoq:ble", "east>pi5:ble"}
    assert blind["pred"] is None                        # never "empty" while blind
    assert at(states, 28)["health"]["status"] == "ok" and at(states, 28)["pred"] is not None
    got = kinds(brain)
    assert got.count("blind_on") == 1 and got.count("blind_off") == 1


def test_the_tray_shows_up_as_an_object_and_in_the_xray():
    brain, feed = taught()
    brain.pop_events()
    states = []
    # The x-ray's static rule is std < 0.8 dB on raw readings, so this needs a quieter feed
    # than sim's default 1 dB noise (issue raised).
    feed.play("tray_t1", seed=3, states=states, noise_db=0.4)   # tray at T1 (1.0, 0.2) from 25 to 55 s
    assert at(states, 20)["objects"] == []
    placed = at(states, 45)
    assert len(placed["objects"]) == 1 and placed["objects"][0]["near"] == "pi5"
    assert placed["pred"]["kind"] != "person"
    xray = placed["xray"]
    assert len(xray["static_db"]) == xray["w"] * xray["h"] and max(xray["static_db"]) > 1
    assert "object_on" in kinds(brain)


def test_only_the_meta_for_our_record_start_opens_a_session():
    """sim.send sends its own demo meta after the bus's one, and again on every loop."""
    brain = Brain()
    feed = Feed(brain)
    brain.on_cmd(cmd("baseline"))
    feed.play("empty_room", seed=1)
    brain.on_cmd(cmd("record_start", session="s07", purpose="train", walker="w1"))
    feed.play("zone_tour", seed=2, meta={"session": "s07", "purpose": "train", "walker": "w1"})   # the bus's meta
    kept = len(brain.open_session["messages"])
    feed.play("zone_tour", seed=3)                       # the feed loops: meta "sim-zone_tour", purpose demo
    assert brain.open_session["meta"]["session"] == "s07" and len(brain.open_session["messages"]) > kept
    brain.on_cmd(cmd("record_stop"))
    feed.play("zone_tour", seed=4, meta={"session": "s07", "purpose": "train", "walker": "w1"})
    assert brain.open_session is None                    # no record_start: nothing opens
    brain.on_cmd(cmd("train"))
    assert brain.state()["model"]["train_sessions"] == ["s07"]
    assert "trained" in [e["kind"] for e in brain.events]


def test_a_failed_fit_leaves_the_old_model_and_clears_training():
    brain, _ = taught(spawn=lambda fit, done: done(None))
    assert brain.model is None and brain.training is None and brain.events[-1]["kind"] != "trained"
