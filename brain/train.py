"""Train the room model on the board (scikit-learn random forests).

Three forests share one feature vector per window (brain/features.py):
- zone: classes 0-4 (0 = empty), so its probabilities are exactly the
  contract's probs = [empty, z1, z2, z3, z4]. present = zone != 0.
- motion: moving / still, trained on windows with someone present.
- kind: person / object / none.

A session is {"meta": <meta message>, "messages": [...]}: meta carries session,
purpose and walker (CONTRACTS.md section 4). Windows from different sessions
never mix, because each session is windowed on its own.

kind follows section 6. A person present -> person. In label_mode object, a
window is "object" only when nobody was in frame for the last 2 s and a link
held a steady drop over them (features.steady_drop); with nobody in frame and
no steady drop it is "none"; with anybody in frame it is left out of training.
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional

import numpy as np
from sklearn.ensemble import RandomForestClassifier

from brain import features as F
from brain import layout

ZONES = [0] + layout.zone_ids()   # empty, then one per zone in radio/nodes.json
FOREST = dict(n_estimators=60, max_depth=12, min_samples_leaf=2, n_jobs=4, random_state=0)
ZONE_SET_MIN_P = 0.25  # a zone joins zone_set when its probability is at least this
UNSEEN_DB = 6.0        # a feature this far outside everything seen in training = "not sure"


def kind_of(window: dict) -> Optional[str]:
    """person | object | none for a labeled window, or None to leave it out of training."""
    label = window["label"]
    if label.get("mode") == "object":
        if window["persons_2s"] > 0:
            return None   # someone is placing the object, or standing next to the square
        return "object" if window["steady_links"] else "none"
    return "person" if label["present"] else "none"


def dataset(sessions: List[dict], base: Dict[str, float], links=F.LINKS) -> dict:
    """Labeled windows from every session, as arrays. links = the layout's links, in order."""
    X, zone, motion, kind, walker, session = [], [], [], [], [], []
    for s in sessions:
        meta = s.get("meta") or {}
        # A session is windowed against the baseline it was recorded on, when that is known:
        # recordings from before a re-baseline keep their own drops.
        for w in F.windows(s["messages"], s.get("base") or base, links):
            lb = w["label"]
            k = kind_of(w) if lb is not None else None
            if k is None:
                continue
            X.append(F.vector(w, links))
            zone.append(lb["zone"])
            motion.append(lb["motion"] or "")
            kind.append(k)
            walker.append(meta.get("walker"))
            session.append(meta.get("session"))
    return {
        "X": np.asarray(X, dtype=float).reshape(-1, len(F.feature_names(links))),
        "zone": np.asarray(zone), "motion": np.asarray(motion), "kind": np.asarray(kind),
        "walker": np.asarray(walker, dtype=object), "session": np.asarray(session, dtype=object),
    }


class Model:
    # The walkers whose windows the forests were fit on (pseudonyms from the sessions' meta).
    # None = unknown: not fit yet, or a model file from before this was kept. That is not the
    # same as [], a fit whose windows had no walker at all (empty room and object sessions only).
    # A class default, so an older pickle without the attribute reads as unknown.
    train_walkers: Optional[List[str]] = None

    def __init__(self, base: Dict[str, float], ver: str = "m1", links=F.LINKS, zones=ZONES[1:]):
        """links and zones come from radio/nodes.json (the brain passes them); the defaults are
        the 2 x 2 m square's. probs has one entry for empty, then one per zone, in that order."""
        self.base = dict(base)
        self.ver = ver
        self.links = tuple(links)
        self.classes = [0] + [int(z) for z in zones]
        self.zone = self.motion = self.kind = None
        self.train_s: Optional[float] = None
        self.windows = 0
        self.train_sessions: List[str] = []
        self.features: List[str] = F.feature_names(self.links)   # what the forests were fit on; checked when a file is loaded
        self.seen_lo = self.seen_hi = None             # per feature, the range seen in training
        self._link_weight = np.zeros(len(self.links))

    @property
    def trained(self) -> bool:
        return self.zone is not None

    def fit(self, sessions: List[dict]) -> "Model":
        t0 = time.monotonic()
        d = dataset(sessions, self.base, self.links)
        if len(d["X"]) == 0:
            raise ValueError("no labeled windows to train on")
        self.zone = _forest(d["X"], d["zone"])
        moving = d["zone"] != 0
        self.motion = _forest(d["X"][moving], d["motion"][moving]) if moving.any() else None
        self.kind = _forest(d["X"], d["kind"])
        # How much each link matters to the zone forest, for the "why" list.
        imp = self.zone.feature_importances_.reshape(len(self.links), len(F.STATS))
        self._link_weight = imp.sum(axis=1)
        self.seen_lo, self.seen_hi = d["X"].min(axis=0), d["X"].max(axis=0)
        self.train_s = time.monotonic() - t0
        self.windows = len(d["X"])
        self.train_sessions = sorted({s for s in d["session"] if s})
        self.train_walkers = sorted({str(w).strip() for w in d["walker"] if w is not None and str(w).strip()})
        return self

    def predict(self, window: dict) -> dict:
        """The contract's pred block for one window (still_s is the alert's job)."""
        x = np.asarray([F.vector(window, self.links)], dtype=np.float32)   # the trees' own input type
        probs = _probs(self.zone, x, self.classes)
        zone = self.classes[int(np.argmax(probs))]
        kind = str(_pick(self.kind, x))
        present = zone != 0
        if present:
            kind = "person"
        elif kind == "person":
            kind = "none"  # the zone forest says empty; never report a person nowhere
        motion = None
        if present and self.motion is not None:
            motion = str(_pick(self.motion, x)) or None
        zone_set = ([z for i, z in enumerate(self.classes) if z and probs[i] >= ZONE_SET_MIN_P] or [zone]) \
            if present else []
        if present and not self.familiar(x[0]):
            # Somebody is there, but the links read like nothing the model was taught: say
            # "not sure where" (every zone it knows) instead of naming one zone as if it knew.
            zone_set = [z for z in self.classes[1:] if z in self.zone.classes_] or zone_set
        return {
            "present": present, "kind": kind, "zone": zone,   # 0 = nobody there (section 3)
            "zone_set": zone_set, "probs": [round(float(p), 3) for p in probs],
            "motion": motion, "still_s": None, "why": self.why(window),
        }

    def familiar(self, x) -> bool:
        """False when some feature lies more than UNSEEN_DB outside the range seen in training."""
        if self.seen_lo is None:
            return True
        return bool(np.all(x >= self.seen_lo - UNSEEN_DB) and np.all(x <= self.seen_hi + UNSEEN_DB))

    def why(self, window: dict, top: int = 2) -> List[str]:
        """Links that most explain this decision: importance x how far they dropped."""
        score = []
        for i, link in enumerate(self.links):
            s = window["links"].get(link) or {}
            score.append(self._link_weight[i] * abs(s.get("drop_db") or 0.0))
        order = np.argsort(score)[::-1]
        return [self.links[i] for i in order[:top] if score[i] > 0]

    def info(self) -> dict:
        """The contract's model block (ms_per_decision is measured by the live loop).

        train_walkers is kept on the model and in model.pkl but is not in this block: section 5's
        model block has no field for it yet."""
        return {"trained": self.trained, "ver": self.ver,
                "train_s": None if self.train_s is None else round(self.train_s, 1),
                "windows": self.windows, "train_sessions": self.train_sessions}


def _forest(X, y) -> RandomForestClassifier:
    forest = RandomForestClassifier(**FOREST).fit(X, y)
    # Train on 4 cores, predict on 1: one window at a time, process pools
    # cost far more than the trees.
    forest.n_jobs = 1
    return forest


def _forest_proba(forest, x) -> np.ndarray:
    """forest.predict_proba(x)[0] for one float32 row, without the forest's per-call overhead.

    A forest's probability is the mean of its trees' probabilities. Asking each tree directly
    (the public predict_proba, input check off) gives the same numbers bit for bit, and skips
    the job dispatch and input validation the forest repeats for every tree: for one window at
    a time that overhead is most of the cost, and the decision runs ten times a second on the
    live loop. Anything unexpected falls back to the forest's own call.
    """
    try:
        total = np.zeros(len(forest.classes_))
        for tree in forest.estimators_:
            total += tree.predict_proba(x, check_input=False)[0]
        return total / len(forest.estimators_)
    except Exception:
        return forest.predict_proba(x)[0]


def _pick(forest, x):
    """forest.predict(x)[0]: the class with the highest mean probability."""
    return forest.classes_[int(np.argmax(_forest_proba(forest, x)))]


def _probs(forest, x, classes) -> np.ndarray:
    """Probabilities over every class in `classes`, 0 for ones never seen in training."""
    out = np.zeros(len(classes))
    p = _forest_proba(forest, x)
    for c, v in zip(forest.classes_, p):
        if int(c) in classes:   # a zone the layout doesn't have can't be answered
            out[classes.index(int(c))] = v
    return out


def leave_one_person_out(sessions: List[dict], base: Dict[str, float]) -> dict:
    """Zone score where each walker is tested on a model that never saw them.

    Sessions without a walker (empty room, objects) are always in training.
    """
    walkers = sorted({(s.get("meta") or {}).get("walker") for s in sessions} - {None})
    correct = total = 0
    per_walker = {}
    for w in walkers:
        train = [s for s in sessions if (s.get("meta") or {}).get("walker") != w]
        test = [s for s in sessions if (s.get("meta") or {}).get("walker") == w]
        model = Model(base).fit(train)
        d = dataset(test, base)
        n = len(d["X"])
        c = int((model.zone.predict(d["X"]) == d["zone"]).sum()) if n else 0
        per_walker[w] = {"correct": c, "total": n}
        correct += c
        total += n
    return {"correct": correct, "total": total, "walkers": len(walkers), "per_walker": per_walker,
            "method": "leave-one-person-out"}
