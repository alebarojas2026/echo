import json

import pytest

from proof.score import BrainReplay, cluster_interval, load_session, object_evidence, score, threshold_zone, truth


def session(name="test", purpose="heldout", zone=0):
    meta = dict(v=2, type="meta", recv_t=0, t=999999, src="live", session=name, purpose=purpose, walker="w1")
    messages = [meta] + [dict(v=2, type="label", recv_t=t, t=999999-t, src="live", zone=zone,
                              present=bool(zone), persons_in_frame=int(bool(zone)), mode="person",
                              clipped=False) for t in range(0, 2100, 100)]
    return {"meta": meta, "messages": messages}


class FakeReplay:
    train_sessions = {"train"}
    train_s = 1.25
    base = {"east>pi5:ble": -50}

    def __init__(self, zones=(0,) * 11):
        self.zones = zones

    def replay(self, session):
        for i, zone in enumerate(self.zones):
            yield dict(end=1000+i*100, pred=None if zone is None else
                       dict(zone=zone or None, present=bool(zone), kind="person" if zone else "none"),
                       links={"east>pi5:ble": {"drop_db": 5 if zone else 0}}, ms=2+i)


def test_recv_t_majority_and_clipped_labels():
    s = session(zone=4)
    assert truth(s["messages"], 1000)["zone"] == 4
    s["messages"][1]["clipped"] = True
    assert truth(s["messages"], 1000) is None
    assert truth([], 1000) is None


def test_scores_counts_baseline_and_null_unmeasured_values():
    result = score([session(zone=4)], FakeReplay((4,) * 11), commit="abc")
    assert result["zone"]["correct"] == result["zone"]["total"] == 11
    assert result["threshold_zone"] == {"correct": 11, "total": 11}
    assert result["person_vs_object"]["correct"] == 11
    assert result["zone"]["ci95"] is None
    assert result["train_s"] is None and result["ms_per_decision"]["p50"] is None
    assert result["bytes_out"] is None and result["images_stored"] is None
    assert result["watts"]["idle"] is None and result["commit"] == "abc"


def test_false_presence_episodes_and_nonoverlapping_empty_time():
    result = score([session()], FakeReplay((0, 4, 4, 0, 4, 4, 0, 0, 0, 0, 0)))
    assert result["false_alarms_per_min"] == 120  # two episodes / one observed second


def test_blind_and_unlabeled_are_not_empty_predictions():
    result = score([session()], FakeReplay((None,) * 11))
    assert result["zone"]["total"] is None and result["false_alarms_per_min"] is None
    result = score([], FakeReplay())
    assert result["threshold_zone"]["total"] is None


@pytest.mark.parametrize("sessions", [[session("train")], [session(purpose="train")], [session(), session()]])
def test_no_training_leakage_or_duplicate_sessions(sessions):
    with pytest.raises(ValueError):
        score(sessions, FakeReplay())


def test_synthetic_is_not_live_proof():
    s = session()
    s["messages"][1]["src"] = "sim"
    with pytest.raises(ValueError):
        score([s], FakeReplay())
    assert score([s], FakeReplay(), allow_sim=True)["zone"]["total"] == 11


def test_intervals_bootstrap_sessions_and_timing_gate():
    assert cluster_interval([(10, 10), (0, 10)]) == [0, 1]
    result = score([session()], FakeReplay(), on_board=True)
    assert result["ms_per_decision"] == {"p50": 7, "p95": 11.5}
    assert result["train_s"] == 1.25


def test_object_truth_requires_no_people_and_stable_radio_history():
    s = session()
    for m in s["messages"][1:]:
        m["mode"] = "object"
    assert truth(s["messages"], 1000) is None
    assert truth(s["messages"], 2100)["kind"] == "object"
    radio = [dict(type="rssi", link="east>pi5:ble", recv_t=t, dbm=-55) for t in range(0, 2500, 100)]
    assert object_evidence(radio, 2500, FakeReplay.base)
    for message in radio[-5:]:
        message["dbm"] = -49
    assert not object_evidence(radio, 2500, FakeReplay.base)
    s["messages"][5]["persons_in_frame"] = 1
    assert truth(s["messages"], 2100) is None


def test_bus_jsonl_requires_recv_t_and_one_meta(tmp_path):
    path = tmp_path / "session.jsonl"
    s = session()
    path.write_text("\n".join(json.dumps(m) for m in reversed(s["messages"])))
    assert load_session(path)["messages"][0]["recv_t"] == 0
    s["messages"][1].pop("recv_t")
    path.write_text("\n".join(json.dumps(m) for m in s["messages"]))
    with pytest.raises(ValueError):
        load_session(path)


def test_fixed_threshold_baseline():
    assert threshold_zone({"west>pi5:ble": {"drop_db": 3}}) == 3
    assert threshold_zone({"west>pi5:ble": {"drop_db": 2.9}}) == 0
    assert threshold_zone({}) is None


def test_real_brain_replay_never_receives_camera_truth():
    pytest.importorskip("brain.core")
    from brain.features import LINKS

    class Model:
        train_sessions = ["train"]
        train_s = None
        def predict(self, window):
            assert window["label"] is None
            return dict(present=True, zone=4, kind="person", motion="moving", why=[])
        def why(self, window):
            return []

    s = session(zone=4)
    for t in range(0, 2200, 100):
        for link in LINKS:
            s["messages"].append(dict(v=2, type="rssi", recv_t=t, t=-t, src="live", link=link, dbm=-55))
    s["messages"].sort(key=lambda m: m["recv_t"])
    replay = BrainReplay(Model(), dict.fromkeys(LINKS, -50), dict.fromkeys(LINKS, 10))
    rows = list(replay.replay(s))
    assert rows and all(row["pred"]["zone"] == 4 for row in rows)


def test_sim_paths_match_the_exact_proof_schema():
    from brain.features import LINKS, Windower
    from brain.tests.simdata import sim_to_v2

    class SimReplay(FakeReplay):
        base = dict.fromkeys(LINKS, -50)
        def replay(self, session):
            windows = Windower(self.base)
            for message in session["messages"]:
                for window in windows.push(message):
                    yield dict(end=window["end"], pred=dict(present=False, zone=None, kind="none"),
                               links=window["links"], ms=None)

    sessions = []
    for name in ("zone_tour", "empty_room"):
        messages = sim_to_v2(name)
        meta = dict(v=2, type="meta", t=messages[0]["t"], recv_t=messages[0]["recv_t"], seq=1,
                    src="sim", session=name, purpose="heldout", walker="synthetic")
        sessions.append(dict(meta=meta, messages=[meta] + [m for m in messages if m["type"] != "meta"]))
    result = score(sessions, SimReplay(), allow_sim=True)
    assert result["zone"]["total"] and result["threshold_zone"]["total"]
    expected = {
        "zone": {"correct", "total", "ci95", "sessions", "walkers", "method"},
        "threshold_zone": {"correct", "total"},
        "person_vs_object": {"correct", "total", "tray_placements"},
        "ms_per_decision": {"p50", "p95"},
        "watts": {"idle", "teaching", "radio_only", "source"},
    }
    assert set(result) == set(expected) | {"false_alarms_per_min", "train_s", "bytes_out",
                                          "images_stored", "models_on_board", "measured_at", "commit"}
    for key, fields in expected.items():
        assert set(result[key]) == fields
