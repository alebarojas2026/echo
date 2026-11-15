"""The decision's short path through the trees gives exactly what scikit-learn's forest gives."""
import numpy as np

from brain import features as F
from brain import train
from brain.tests.simdata import sim_to_v2


def trained():
    base = F.baseline(sim_to_v2("empty_room", seed=1))
    sessions = [{"meta": {"session": name, "purpose": purpose, "walker": walker},
                 "messages": sim_to_v2(path, seed=seed, mode=mode)}
                for name, path, purpose, walker, seed, mode in [
                    ("s01", "empty_room", "train", None, 2, None), ("s02", "tray_t1", "object", None, 4, "object"),
                    ("s10", "zone_tour", "train", "w1", 10, None), ("s11", "stand_still", "train", "w2", 11, None)]]
    return train.Model(base).fit(sessions), base


def test_every_decision_matches_the_forests_own_answer_exactly():
    model, base = trained()
    n = 0
    for path, seed in (("zone_tour", 20), ("tray_t1", 21), ("wave_checkin", 22), ("dropped_link", 23)):
        for window in F.windows(sim_to_v2(path, seed=seed), base):
            x = np.asarray([F.vector(window)], dtype=float)
            pred = model.predict(window)
            want = model.zone.predict_proba(x)[0]
            got = train._forest_proba(model.zone, x.astype(np.float32))
            assert np.array_equal(got, want)                       # bit for bit, not "close"
            assert train._pick(model.kind, x.astype(np.float32)) == model.kind.predict(x)[0]
            assert train._pick(model.motion, x.astype(np.float32)) == model.motion.predict(x)[0]
            assert pred["zone"] == int(model.zone.predict(x)[0])
            n += 1
    assert n > 1000


def test_a_forest_whose_trees_cannot_be_asked_directly_falls_back_to_its_own_call():
    class Odd:                                   # trees of a kind this code doesn't know
        classes_ = np.array(["person", "none"])
        estimators_ = [object(), object()]

        def predict_proba(self, x):
            return np.array([[0.2, 0.8]])

    x = np.zeros((1, 3), dtype=np.float32)
    assert list(train._forest_proba(Odd(), x)) == [0.2, 0.8]
    assert train._pick(Odd(), x) == "none"
