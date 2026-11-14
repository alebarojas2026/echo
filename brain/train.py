"""Train the room model on the board (scikit-learn random forests).

Three forests share one feature vector per window (brain/features.py):
- zone: classes 0-4 (0 = empty), so its probabilities are exactly the
  contract's probs = [empty, z1, z2, z3, z4]. present = zone != 0.
- motion: moving / still, trained on windows with someone present.
- kind: person / object / none.

A session is {"meta": <meta message>, "messages": [...]}: meta carries session,
purpose and walker (CONTRACTS.md section 4). Windows from different sessions
never mix, because each session is windowed on its own.

kind comes from the label: present -> person; label_mode object -> object;
otherwise none. The section 6 object rule (persons_in_frame 0, a steady drop)
is enforced by the teacher when it emits object-mode labels.
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional

import numpy as np
from sklearn.ensemble import RandomForestClassifier

from brain import features as F

ZONES = [0, 1, 2, 3, 4]
FOREST = dict(n_estimators=60, max_depth=12, min_samples_leaf=2, n_jobs=4, random_state=0)
ZONE_SET_MIN_P = 0.25  # a zone joins zone_set when its probability is at least this


def kind_of(label: dict) -> str:
    if label["present"]:
        return "person"
    return "object" if label.get("mode") == "object" else "none"


def dataset(sessions: List[dict], base: Dict[str, float]) -> dict:
    """Labeled windows from every session, as arrays."""
    X, zone, motion, kind, walker, session = [], [], [], [], [], []
    for s in sessions:
        meta = s.get("meta") or {}
        for w in F.windows(s["messages"], base):
            lb = w["label"]
            if lb is None:
                continue
            X.append(F.vector(w))
            zone.append(lb["zone"])
            motion.append(lb["motion"] or "")
            kind.append(kind_of(lb))
            walker.append(meta.get("walker"))
            session.append(meta.get("session"))
    return {
        "X": np.asarray(X, dtype=float).reshape(-1, len(F.feature_names())),
        "zone": np.asarray(zone), "motion": np.asarray(motion), "kind": np.asarray(kind),
        "walker": np.asarray(walker, dtype=object), "session": np.asarray(session, dtype=object),
    }


class Model:
    def __init__(self, base: Dict[str, float], ver: str = "m1"):
        self.base = dict(base)
        self.ver = ver
        self.zone = self.motion = self.kind = None
        self.train_s: Optional[float] = None
        self.windows = 0
        self.train_sessions: List[str] = []
        self._link_weight = np.zeros(len(F.LINKS))

    @property
    def trained(self) -> bool:
        return self.zone is not None

    def fit(self, sessions: List[dict]) -> "Model":
        t0 = time.monotonic()
        d = dataset(sessions, self.base)
        if len(d["X"]) == 0:
            raise ValueError("no labeled windows to train on")
        self.zone = _forest(d["X"], d["zone"])
        moving = d["zone"] != 0
        self.motion = _forest(d["X"][moving], d["motion"][moving]) if moving.any() else None
        self.kind = _forest(d["X"], d["kind"])
        # How much each link matters to the zone forest, for the "why" list.
        imp = self.zone.feature_importances_.reshape(len(F.LINKS), len(F.STATS))
        self._link_weight = imp.sum(axis=1)
        self.train_s = time.monotonic() - t0
        self.windows = len(d["X"])
        self.train_sessions = sorted({s for s in d["session"] if s})
        return self

    def predict(self, window: dict) -> dict:
        """The contract's pred block for one window (still_s is the alert's job)."""
        x = np.asarray([F.vector(window)], dtype=float)
        probs = _probs(self.zone, x, ZONES)
        zone = int(np.argmax(probs))
        kind = str(self.kind.predict(x)[0])
        present = zone != 0
        if present:
            kind = "person"
        elif kind == "person":
            kind = "none"  # the zone forest says empty; never report a person nowhere
        motion = None
        if present and self.motion is not None:
            motion = str(self.motion.predict(x)[0]) or None
        zone_set = [z for z in ZONES[1:] if probs[z] >= ZONE_SET_MIN_P] or ([zone] if present else [])
        return {
            "present": present, "kind": kind, "zone": zone if present else None,
            "zone_set": zone_set, "probs": [round(float(p), 3) for p in probs],
            "motion": motion, "still_s": None, "why": self.why(window),
        }

    def why(self, window: dict, top: int = 2) -> List[str]:
        """Links that most explain this decision: importance x how far they dropped."""
        score = []
        for i, link in enumerate(F.LINKS):
            s = window["links"].get(link) or {}
            score.append(self._link_weight[i] * abs(s.get("drop_db") or 0.0))
        order = np.argsort(score)[::-1]
        return [F.LINKS[i] for i in order[:top] if score[i] > 0]

    def info(self) -> dict:
        """The contract's model block (ms_per_decision is measured by the live loop)."""
        return {"trained": self.trained, "ver": self.ver,
                "train_s": None if self.train_s is None else round(self.train_s, 1),
                "windows": self.windows, "train_sessions": self.train_sessions}


def _forest(X, y) -> RandomForestClassifier:
    forest = RandomForestClassifier(**FOREST).fit(X, y)
    # Train on 4 cores, predict on 1: one window at a time, process pools
    # cost far more than the trees.
    forest.n_jobs = 1
    return forest


def _probs(forest, x, classes) -> np.ndarray:
    """Probabilities over every class in `classes`, 0 for ones never seen in training."""
    out = np.zeros(len(classes))
    p = forest.predict_proba(x)[0]
    for c, v in zip(forest.classes_, p):
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
