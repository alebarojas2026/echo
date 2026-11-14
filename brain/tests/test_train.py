import time

import pytest

from brain import features as F
from brain import train as T
from brain.tests.simdata import sim_to_v2


def session(name, path, walker=None, seed=0, mode="person", purpose="train"):
    return {"meta": {"type": "meta", "session": name, "purpose": purpose, "walker": walker},
            "messages": sim_to_v2(path, seed=seed, mode=mode)}


@pytest.fixture(scope="module")
def base():
    return F.baseline(sim_to_v2("empty_room", seed=99))


@pytest.fixture(scope="module")
def sessions():
    out = [session("s01", "empty_room", seed=10), session("s02", "metal_object", seed=11, mode="object")]
    for i, w in enumerate(["w1", "w2", "w3"]):
        out.append(session(f"t{i}", "zone_tour", walker=w, seed=20 + i))
        out.append(session(f"st{i}", "stand_still", walker=w, seed=30 + i))
    return out


@pytest.fixture(scope="module")
def model(base, sessions):
    return T.Model(base).fit(sessions)


def test_dataset_shapes(base, sessions):
    d = T.dataset(sessions, base)
    n = len(d["X"])
    assert n > 1000 and d["X"].shape[1] == len(F.feature_names())
    assert all(len(d[k]) == n for k in ("zone", "motion", "kind", "walker", "session"))
    assert set(d["kind"]) == {"person", "object", "none"}
    assert set(d["zone"]) == {0, 1, 2, 3, 4}


def test_train_is_fast_and_reports_info(model):
    info = model.info()
    assert info["trained"] and info["windows"] > 1000
    assert info["train_s"] < 60
    assert info["train_sessions"] == sorted(["s01", "s02", "t0", "t1", "t2", "st0", "st1", "st2"])


def test_pred_matches_contract(model, base):
    w = next(win for win in F.windows(sim_to_v2("zone_tour", seed=5), base)
             if win["label"] and win["label"]["present"])
    pred = model.predict(w)
    assert set(pred) == {"present", "kind", "zone", "zone_set", "probs", "motion", "still_s", "why"}
    assert len(pred["probs"]) == 5 and sum(pred["probs"]) == pytest.approx(1, abs=0.01)
    assert pred["kind"] in ("person", "object", "none")
    assert pred["motion"] in ("moving", "still", None)
    assert all(link in F.LINKS for link in pred["why"])
    if pred["present"]:
        assert pred["zone"] in pred["zone_set"] and pred["kind"] == "person"


def test_empty_room_predicts_empty(model, base):
    ws = list(F.windows(sim_to_v2("empty_room", seed=7), base))
    preds = [model.predict(w) for w in ws]
    assert sum(not p["present"] for p in preds) / len(preds) > 0.9
    assert all(p["zone"] is None for p in preds if not p["present"])


def test_object_is_not_a_person(model, base):
    ws = list(F.windows(sim_to_v2("metal_object", seed=8), base))
    kinds = [model.predict(w)["kind"] for w in ws]
    assert kinds.count("object") / len(kinds) > 0.8


def test_untrained_model_refuses_empty_data(base):
    with pytest.raises(ValueError):
        T.Model(base).fit([{"meta": {}, "messages": []}])


def test_leave_one_person_out_beats_chance(base, sessions):
    t0 = time.monotonic()
    score = T.leave_one_person_out(sessions, base)
    assert score["walkers"] == 3 and set(score["per_walker"]) == {"w1", "w2", "w3"}
    assert score["total"] > 0
    # Chance on 5 classes is 0.2; sim is clean, so expect far better.
    assert score["correct"] / score["total"] > 0.6
    assert time.monotonic() - t0 < 120
