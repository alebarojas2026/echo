import time

import pytest

from brain import features as F
from brain import train as T
from brain.tests.simdata import T0_MS, sim_to_v2


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
    assert all(p["zone"] == 0 for p in preds if not p["present"])   # 0 = empty, never null


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


def test_only_the_placed_stretch_trains_as_object(base):
    """tray_t1: empty 25 s, tray down 25-55 s, then away. Object mode throughout."""
    t0 = T0_MS
    msgs = sim_to_v2("tray_t1", seed=4, mode="object")
    for m in msgs:
        # Someone stands next to the square (in frame, not present) from 40 to 44 s.
        if m["type"] == "label" and 40_000 <= m["recv_t"] - t0 < 44_000:
            m["persons_in_frame"] = 1
    kinds = {}
    for w in F.windows(msgs, base):
        if w["label"] is not None:
            kinds[(w["end"] - t0) / 1000] = T.kind_of(w)

    def share(kind, lo, hi):
        got = [k for t, k in kinds.items() if lo <= t < hi]
        return sum(k == kind for k in got) / len(got)

    assert share("none", 3, 25) == 1.0            # before the tray goes down
    assert share("object", 28, 40) > 0.8          # placed, nobody around
    assert share(None, 41, 44) == 1.0             # somebody in frame: left out
    assert share(None, 44, 45.8) == 1.0           # and for 2 s after they leave
    assert share("object", 47, 55) > 0.8
    assert share("none", 58, 60) == 1.0           # after it is taken away
    d = T.dataset([{"meta": {"session": "o1", "purpose": "object"}, "messages": msgs}], base)
    assert set(d["kind"]) == {"object", "none"} and len(d["X"]) < len(kinds)


def test_person_standing_still_is_never_an_object(base):
    ws = [w for w in F.windows(sim_to_v2("stand_still", seed=2), base) if w["label"]]
    assert {T.kind_of(w) for w in ws} == {"person", "none"}


def test_zone_set_is_empty_when_nobody_is_present(model, base):
    preds = [model.predict(w) for w in F.windows(sim_to_v2("empty_room", seed=12), base)]
    assert all(p["zone_set"] == [] for p in preds if not p["present"])
    assert any(not p["present"] for p in preds)


# ---- which walkers a model was fit on (#580) ----

def test_fit_keeps_the_walkers_whose_windows_it_used(model):
    assert model.train_walkers == ["w1", "w2", "w3"]        # the empty-room and object sessions have none


def test_walkers_unknown_is_not_the_same_as_no_walkers(base):
    assert T.Model(base).train_walkers is None               # not fit yet: unknown
    only_empty = T.Model(base).fit([session("s01", "empty_room", seed=10)])
    assert only_empty.train_walkers == []                    # fit, and known to have no walker


def test_blank_walker_ids_are_not_counted(base):
    fit = T.Model(base).fit([session("a", "zone_tour", walker="  ", seed=1),
                             session("b", "zone_tour", walker=" w9 ", seed=2)])
    assert fit.train_walkers == ["w9"]


def test_a_session_without_fitted_windows_adds_no_walker(base):
    clipped = session("c", "zone_tour", walker="w5", seed=3)
    for m in clipped["messages"]:
        if m["type"] == "label":
            m["clipped"] = True                              # every window is dropped
    fit = T.Model(base).fit([session("a", "zone_tour", walker="w1", seed=1), clipped])
    assert fit.train_walkers == ["w1"] and "c" not in fit.train_sessions


def test_walkers_survive_pickling_and_an_older_file_reads_as_unknown(model):
    import pickle
    again = pickle.loads(pickle.dumps(model))
    assert again.train_walkers == ["w1", "w2", "w3"]
    legacy = pickle.loads(pickle.dumps(model))
    del legacy.__dict__["train_walkers"]                      # a model file from before this was kept
    legacy = pickle.loads(pickle.dumps(legacy))
    assert legacy.train_walkers is None and legacy.trained    # still usable, but never walker-independent
    assert "train_walkers" not in model.info()                # section 5's model block has no field for it
