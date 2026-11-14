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
    assert [e["kind"] for e in brain.pop_events()] == ["baseline_done", "cam_on"]   # cam_on with the first state
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
    assert brain.watch.still_ms == 0


def test_router_off_home_means_no_pred(ready):
    brain, feed = ready
    brain.on_cmd(cmd("router_moved", spot="S-W30"))
    feed.play("zone_tour", seed=6)
    s = brain.state()
    assert s["router"] == "S-W30" and s["pred"] is None
    brain.on_cmd(cmd("router_home"))
    feed.play("empty_room", seed=7)          # the room is clear, so the 3 s check passes
    assert brain.state()["router"] == "S-home" and brain.pred is not None and not brain.recalibrating
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
    assert [(e["kind"], e["info"]) for e in events] == [("reset", {}), ("recording", {"on": False})]   # no nulls in info
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


def test_standing_still_alerts_and_a_wave_checks_in():
    led_calls = []

    class Led:
        def show_zone(self, n): led_calls.append(("show_zone", n))
        def alert(self, on): led_calls.append(("alert", on))
        def smile(self): led_calls.append(("smile",))

    brain, feed = taught(led=Led())
    brain.pop_events()
    del led_calls[:]
    states = []
    feed.play("wave_checkin", seed=1, states=states)    # still in zone 4 from 1 s, waves at 14-16.5 s
    assert at(states, 6)["alert"]["state"] == "counting" and at(states, 6)["alert"]["limit_s"] == 10
    assert at(states, 13.5)["alert"] == dict(at(states, 13.5)["alert"], state="check_on", zone=4)
    assert at(states, 13.5)["pred"]["still_s"] >= 10
    after = at(states, 18)
    assert after["alert"]["state"] == "counting" and after["checkin"]["link"] == "pi5>unoq:wifi"
    got = [k for k in kinds(brain) if k in ("alert_on", "checkin", "alert_off")]
    assert got == ["alert_on", "checkin", "alert_off"]
    assert [c for c in led_calls if c[0] != "show_zone"] == [("alert", True), ("smile",), ("alert", False)]
    brain.on_cmd(cmd("reset"))
    assert brain.state()["checkin"] is None


def test_a_link_is_listed_once_it_has_a_reading():
    brain = Brain()
    msgs = [m for m in sim_to_v2("empty_room") if m["type"] == "rssi"]
    brain.on_message(next(m for m in msgs if m["link"] == "east>pi5:ble"))
    links = brain.state()["links"]
    assert [l["id"] for l in links] == ["east>pi5:ble"]
    assert links[0]["dbm"] is not None and links[0]["base_dbm"] is None and links[0]["drop_db"] is None


# ---- fixes from the post-merge review (#172, #157, #171) ----

def check_all(messages):
    from contracts.check import errors
    return [(m["type"], m.get("kind"), e) for m in messages for e in errors(m)]


def test_every_state_and_event_passes_the_contract_schemas():
    brain, feed = taught()
    out = brain.pop_events()
    for path in ("empty_room", "tray_t1", "dropped_link", "zone_tour"):
        states = []
        feed.play(path, seed=9, states=states)
        out += [s for _, s in states] + brain.pop_events()
    brain.on_cmd(cmd("router_moved", spot="S-W30"))
    brain.on_cmd(cmd("router_home"))
    out += brain.pop_events()
    kinds_seen = {m["kind"] for m in out if m["type"] == "event"}
    assert {"trained", "baseline_done", "recording", "blind_on", "blind_off", "router_moved"} <= kinds_seen
    bad = [b for b in check_all(out) if "pred.motion" not in b[2]]   # motion null is the schema's to fix (#170)
    assert not bad, bad[:5]


def test_nobody_there_is_zone_0_not_null(ready):
    brain, feed = ready
    feed.play("empty_room", seed=4)
    assert brain.pred["present"] is False and brain.pred["zone"] == 0 and brain.pred["zone_set"] == []
    assert brain.pred["motion"] is None and brain.pred["kind"] != "person"
    block = brain.state()["alert"]
    assert block["state"] == "none" and block["zone"] is None      # zone 0 never counts or alerts
    assert not [e for e in brain.pop_events() if e["kind"] in ("alert_on", "checkin")]


def test_a_quiet_link_keeps_its_last_dbm_and_drop():
    brain, feed = taught()
    states = []
    feed.play("dropped_link", seed=3, states=states)     # east is silent from 10 to 20 s
    quiet = {l["id"]: l for l in at(states, 16)["links"]}["east>pi5:ble"]
    before = {l["id"]: l for l in at(states, 9.5)["links"]}["east>pi5:ble"]
    assert quiet["rate_hz"] == 0 and quiet["status"] == "blind"
    assert isinstance(quiet["dbm"], float) and abs(quiet["dbm"] - before["dbm"]) < 3
    assert isinstance(quiet["drop_db"], float)


def baseline_feed(brain, path="empty_room", edit=None, seed=1):
    """Ask for a baseline and play one path. edit(message) may change or drop (return None) messages."""
    brain.on_cmd(cmd("baseline"))
    for m in sim_to_v2(path, seed=seed):
        m = edit(m) if edit else m
        if m:
            brain.on_message(m)


def test_baseline_needs_the_camera_on():
    brain = Brain()
    baseline_feed(brain, edit=lambda m: None if m["type"] in ("cam", "label") else m)
    assert not brain.base and brain.capture is not None      # still waiting, never done blind
    brain2 = Brain()
    baseline_feed(brain2, edit=lambda m: dict(m, state="off") if m["type"] == "cam" else m)
    assert not brain2.base


def test_baseline_needs_every_link_through_the_capture():
    def east_goes_quiet(m):   # east stops 5 s in and never comes back
        return None if m["type"] == "rssi" and m["tx"] == "east" and m["recv_t"] - T0_MS > 5_000 else m

    brain = Brain()
    baseline_feed(brain, edit=east_goes_quiet)
    assert not brain.base

    def east_blips(m):        # east is quiet from 5 to 8 s: the 20 s start again at 8 s
        return None if m["type"] == "rssi" and m["tx"] == "east" and 5_000 < m["recv_t"] - T0_MS < 8_000 else m

    brain = Brain()
    done_at = []
    baseline_feed(brain, edit=lambda m: (done_at.append(m["recv_t"]) if brain.base and not done_at else None,
                                         east_blips(m))[1])
    assert 28_000 <= done_at[0] - T0_MS < 28_400
    assert all(hz > 13 for hz in brain.expected_hz.values())   # counted over a full 20 s


def test_baseline_restarts_if_label_mode_is_turned_on():
    brain = Brain()
    turned_on = []

    def edit(m):
        if not turned_on and m["recv_t"] - T0_MS > 10_000:
            turned_on.append(1)
            brain.on_cmd(cmd("label_mode", mode="person"))
        return m

    baseline_feed(brain, edit=edit)
    assert not brain.base


def test_blind_pauses_the_still_timer():
    brain, feed = taught()
    states = []
    feed.play("dropped_link", seed=3, states=states)     # standing in zone 1; blind from about 13 to 23 s
    before, after = at(states, 12)["pred"]["still_s"], at(states, 27)["pred"]["still_s"]
    assert before > 8
    assert after >= before                               # the time built up is kept across the blind span


def test_ms_per_decision_comes_back_right_after_a_retrain(ready):
    brain, feed = ready
    feed.play("empty_room", seed=6)
    assert brain.state()["model"]["ms_per_decision"] is not None
    brain.on_cmd(cmd("train"))
    brain.on_cmd(cmd("train"))
    model = brain.state()["model"]                       # no new readings since the retrain
    assert model["trained"] and model["ver"] == "m3" and model["ms_per_decision"] is not None


def test_back_to_back_recordings_keep_both_sessions():
    brain = Brain()
    feed = Feed(brain)
    brain.on_cmd(cmd("baseline"))
    feed.play("empty_room", seed=1)
    brain.on_cmd(cmd("record_start", session="a1", purpose="train", walker="w1"))
    feed.play("zone_tour", seed=2, meta={"session": "a1", "purpose": "train", "walker": "w1"})
    brain.on_cmd(cmd("record_start", session="a2", purpose="train", walker="w2"))   # no record_stop first
    feed.play("zone_tour", seed=3, meta={"session": "a2", "purpose": "train", "walker": "w2"})
    brain.on_cmd(cmd("record_stop"))
    assert sorted(brain.sessions) == ["a1", "a2"]
    assert all(len(s["messages"]) > 1000 for s in brain.sessions.values())


def test_src_follows_the_radio_feed_only():
    brain = Brain()
    for m in sim_to_v2("empty_room")[:200]:
        brain.on_message(dict(m, src="live") if m["type"] in ("cam", "label", "meta") else m)
    assert brain.state()["src"] == "sim"                 # the camera and the bus's meta say live


def test_training_block_while_a_fit_runs():
    pending = []
    brain, _ = taught(spawn=lambda fit, done: pending.append((fit, done)))
    training = brain.state()["model"]["training"]
    assert set(training) == {"started_t", "progress", "sessions"} and training["progress"] is None
    assert training["sessions"] == sorted(training["sessions"]) and "s01" in training["sessions"]
    fit, done = pending[0]
    done(fit())
    assert brain.state()["model"]["training"] is None and brain.model.trained


def test_baseline_json_is_written_and_read_back_at_start(tmp_path):
    import json
    brain = Brain(sessions_dir=tmp_path)
    baseline_feed(brain)
    doc = json.loads((tmp_path / "baseline.json").read_text())
    assert set(doc) == {"t", "session", "links"} and doc["session"] is None and doc["t"] > T0_MS
    assert set(doc["links"]) == set(F.LINKS)
    assert doc["links"]["pi5>unoq:wifi"] == {"base_dbm": brain.base["pi5>unoq:wifi"],
                                             "expected_hz": brain.expected_hz["pi5>unoq:wifi"]}
    again = Brain(sessions_dir=tmp_path)                 # a restart picks it up
    assert again.base == brain.base and again.expected_hz == brain.expected_hz
    assert again.windower is not None
    (tmp_path / "baseline.json").write_text("not json")
    assert Brain(sessions_dir=tmp_path).base == {}


# ---- router move, recalibrate, drift and advice (#37) ----

def router_run(brain, feed, path, moved_at, home_at, edit_path=None, drop_camera_after=None, states=None):
    """Play a path, sending router_moved (to the advised spot) and router_home at the given seconds."""
    sent = {}
    t0 = feed.t

    def each(m):
        s = (m["recv_t"] - t0) / 1000
        if s >= moved_at and "moved" not in sent:
            sent["moved"] = brain.advice["to_spot"] if brain.advice else "S-W30"
            brain.on_cmd(cmd("router_moved", spot=sent["moved"]))
        if s >= home_at and "home" not in sent:
            sent["home"] = True
            brain.on_cmd(cmd("router_home"))

    msgs = sim_to_v2(path, seed=3, t0=t0) if edit_path is None else None
    if msgs is None:
        from sim import fake, wire
        import json
        encode = wire.encoder(t0)
        msgs = [json.loads(encode(ev)) for ev in fake.simulate(edit_path(dict(fake.load_path(path))), seed=3)]
        for m in msgs:
            m["recv_t"] = m["t"]
    last = 0
    for m in msgs:
        s = (m["recv_t"] - t0) / 1000
        if drop_camera_after is not None and s > drop_camera_after and m["type"] in ("cam", "label"):
            continue
        brain.on_message(m)
        each(m)
        if states is not None and m["recv_t"] - last >= 100:
            last = m["recv_t"]
            states.append((s, brain.state()))
    feed.t = msgs[-1]["recv_t"] + 100
    return sent


def test_advice_then_router_move_and_home():
    """router_move: tray at T1 from 25 s, router to S-W30 at 45 s (its link clears), tray off at 60, home at 65."""
    brain, feed = taught()
    brain.pop_events()
    states = []
    sent = router_run(brain, feed, "router_move", moved_at=45, home_at=65, states=states)
    assert at(states, 20)["advice"] is None
    shown = at(states, 43)["advice"]
    assert shown["to_spot"] == sent["moved"] == "S-W30" and shown["link"] == "pi5>unoq:wifi"
    assert shown["near"] == "pi5" and shown["after_dbm"] is None and shown["text"]
    base = brain.base["pi5>unoq:wifi"]
    assert base - 12 < shown["before_dbm"] < base - 7             # the tray costs about 10 dB
    assert at(states, 47)["advice"]["after_dbm"] is None          # after_dbm waits 2 s, then takes 3 s
    assert at(states, 47)["pred"] is None                         # router off S-home
    moved = at(states, 52)["advice"]
    assert moved["before_dbm"] == at(states, 44.9)["advice"]["before_dbm"]   # frozen at router_moved
    assert moved["after_dbm"] > moved["before_dbm"] + 4           # the new link clears the tray
    assert at(states, 66)["pred"] is None and at(states, 66)["advice"] is None   # the 3 s check
    assert at(states, 70)["pred"] is not None and at(states, 70)["router"] == "S-home"
    events = [e for e in brain.pop_events() if e["kind"] in
              ("advice", "router_moved", "advice_result", "router_home", "recalibrating", "drift")]
    assert [e["kind"] for e in events] == ["advice", "router_moved", "advice_result", "router_home"]
    assert events[0]["info"]["node"] == "pi5" and events[1]["info"]["before_dbm"] == moved["before_dbm"]
    assert events[2]["info"] == {"link": "pi5>unoq:wifi", "before_dbm": moved["before_dbm"],
                                 "after_dbm": moved["after_dbm"]}
    assert not check_all(events)


def tray_stays(path):   # the tray is never taken off, and the router never really moves
    return dict(path, duration_s=75, router=[{"t": 0, "spot": "S-home"}],
                objects=[dict(path["objects"][0], t_off=1000)])


def test_router_home_with_the_tray_still_on_recalibrates_and_reports_drift():
    brain, feed = taught()
    brain.pop_events()
    old = dict(brain.base)
    states = []
    router_run(brain, feed, "router_move", moved_at=40, home_at=45, edit_path=tray_stays, states=states)
    assert at(states, 47)["pred"] is None                         # checking for 3 s
    assert brain.recalibrating is False and at(states, 60)["pred"] is None   # then a 20 s baseline
    assert at(states, 72)["pred"] is not None                     # done at about 68 s
    assert old["pi5>unoq:wifi"] - brain.base["pi5>unoq:wifi"] > 7  # the tray is in the new baseline
    kinds_seen = [e["kind"] for e in brain.pop_events()
                  if e["kind"] in ("router_home", "recalibrating", "baseline_done", "drift")]
    assert kinds_seen == ["router_home", "recalibrating", "baseline_done", "drift"]
    assert brain.label_mode == "off"


def test_recalibration_also_runs_with_the_camera_unplugged():
    brain, feed = taught()
    router_run(brain, feed, "router_move", moved_at=40, home_at=45, edit_path=tray_stays, drop_camera_after=30)
    assert "baseline_done" in [e["kind"] for e in brain.events[-6:]] and not brain.recalibrating
    # ... but a baseline asked for by hand still waits for the camera.
    brain.on_cmd(cmd("baseline"))
    router_run(brain, feed, "empty_room", moved_at=999, home_at=999, drop_camera_after=0)
    assert brain.capture is not None


def test_reset_clears_the_advice():
    brain, feed = taught()
    states = []
    router_run(brain, feed, "tray_t1", moved_at=999, home_at=999, states=states)
    assert at(states, 45)["advice"] is not None
    brain.on_cmd(cmd("reset"))
    assert brain.advice is None


# ---- the event stream for the narrator (#38) ----

def test_a_session_gives_the_narrator_enter_checkin_object_advice_and_cam_off():
    brain, feed = taught()
    brain.pop_events()
    feed.play("wave_checkin", seed=1, states=[])      # walk into zone 4, stand, wave, walk out
    feed.play("tray_t1", seed=3, states=[])           # the tray at T1 from 25 to 55 s
    feed.play("camera_unplug", seed=2, states=[])     # a zone tour; the camera is unplugged at 14 s
    events = brain.pop_events()
    got = [e["kind"] for e in events]
    for kind in ("enter", "checkin", "object_on", "advice", "cam_off", "exit", "zone_change", "alert_on",
                 "alert_off", "object_off"):
        assert kind in got, kind
    assert not check_all(events)

    def info(kind, n=0):
        return [e["info"] for e in events if e["kind"] == kind][n]

    assert info("enter") == {"zone": 4}
    assert info("checkin") == {"zone": 4, "link": "pi5>unoq:wifi"}
    assert info("exit") == {"zone": 4}                              # where they left from
    assert info("object_on")["node"] == "pi5" and info("advice")["node"] == "pi5"
    assert isinstance(info("advice")["before_dbm"], float)
    assert info("cam_off") == {}
    tour = [e["info"]["zone"] for e in events if e["kind"] in ("enter", "zone_change")][1:]
    assert tour == [3, 4, 2, 1]                                     # the tour's zones, each said once
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs) and len({e["id"] for e in events}) == len(events)


def test_one_flickering_decision_is_not_an_enter():
    brain = Brain()
    for zone in (0, 0, 2, 0, 0, 3, 3, 0):
        brain._announce(zone)
    assert brain.events == []
    for _ in range(5):
        brain._announce(2)
    brain._announce(2)
    assert [(e["kind"], e["info"]) for e in brain.events] == [("enter", {"zone": 2})]


def test_camera_events_follow_the_camera_state():
    brain = Brain()
    t = T0_MS

    def cam(state, after_ms):
        nonlocal t
        t += after_ms
        brain.on_message({"v": 2, "type": "cam", "recv_t": t, "state": state, "fps": 9.0})
        brain.on_message({"v": 2, "type": "rssi", "recv_t": t, "link": "pi5>unoq:wifi", "dbm": -50, "src": "sim"})
        brain.state()

    brain.state()
    assert brain.events == []                 # off at start is not news
    cam("on", 0), cam("on", 1000), cam("stalled", 1000), cam("on", 1000), cam("off", 1000)
    assert [e["kind"] for e in brain.pop_events()] == ["cam_on", "cam_stalled", "cam_on", "cam_off"]
    cam("on", 1000)
    brain.on_message({"v": 2, "type": "rssi", "recv_t": t + 4000, "link": "pi5>unoq:wifi", "dbm": -50, "src": "sim"})
    brain.state()                             # no cam message for over 3 s: it's off
    assert [e["kind"] for e in brain.pop_events()] == ["cam_on", "cam_off"]
