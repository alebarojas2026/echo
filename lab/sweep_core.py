"""The settings sweep without Modal: loading, the sealed held-out set, the variants and the scoring.

lab/sweep.py fans this out on Modal. Everything here also runs on a laptop, so the tests drive it
directly. The brain's own code does the work: brain/features.py makes the windows and the feature
vectors, brain/train.py's forest settings and labels train the model, brain/alert.py's Watch does
the smoothing and the still timer, and proof/score.py's session bootstrap gives the intervals.

Honest testing, in code:
- Tuning reads only sessions whose purpose is train or object (brain.core.TRAIN_PURPOSES).
- Held-out sessions are sealed: each is listed by a hash of its readings and labels in a ledger
  (sweep-out/sealed.json). A session whose hash is in the ledger is refused by every tuning path,
  even if its file is renamed or its purpose is changed. The sealed readings never go into a
  tuning payload, and Sealed.open() hands them out once, after a winner is picked.
- Tuning scores are leave-one-walker-out (and leave-one-desk-out when two desks exist), with 95%
  intervals from a bootstrap over sessions, not over windows.
"""
from __future__ import annotations

import gzip
import hashlib
import itertools
import json
import math
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parent.parent

# --- the grid --------------------------------------------------------------------------------

# Today's settings on main. The defaults are always one of the variants.
DEFAULTS = {"window_ms": 1000, "features": "absolute", "trees": 60, "depth": 12, "links": "all",
            "lesson_s": None, "smooth": [10, 6], "moving_run": 5, "unsure_p": 0.0}

GRID = {
    "window_ms": [600, 1000, 1500, 2000],
    # absolute = main's features (mean, std, min, max in dBm, and drop_db);
    # relative = PR #469's (every feature taken against the link's baseline).
    "features": ["absolute", "relative"],
    # Never bigger than today's 60 trees at depth 12: nothing larger has been timed on the board,
    # and board/bench/README.md says to shrink the forest first when the board is busy.
    "forest": [[15, 8], [30, 10], [60, 12]],
    "links": ["all", "strip_crossing", "four_nodes", "router_receiver"],
    # Seconds of each walker's recording the model is taught on (None = all of it).
    "lesson_s": [None, 10, 20, 30, 45, 60],
    # brain/alert.py: zone and kind are the majority of `smooth[0]` decisions, `smooth[1]` to take
    # over; the still timer resets after `moving_run` moving decisions in a row.
    "smooth": [[5, 3], [10, 6], [15, 9]],
    "moving_run": [3, 5, 8],
    # "Not sure": someone is there but the top zone's probability is under this (0 = never).
    "unsure_p": [0.0, 0.45, 0.55, 0.65],
}
LESSON_CURVE_S = [10, 20, 30, 45, 60]
UNSURE_CREDIT = 0.5     # a "not sure" answer is worth half a right one: better than a wrong zone
STILL_WEIGHT = 0.02     # objective = zone score - this x still-timer error in seconds
MIN_TRAIN_SESSIONS = 4
MIN_WALKERS = 2
DRIFT_DB = 1.0          # brain README: a baseline that moved a link by more than 1 dB is drift
CPU_PER_JOB = 2.0


def model_jobs(grid=GRID) -> List[dict]:
    """One Modal call per model setting; each scores every post setting (smoothing, still timer,
    "not sure") on the same predictions, so those cost no extra training."""
    return [{"window_ms": w, "features": f, "trees": t, "depth": d, "links": l, "lesson_s": s}
            for w, f, (t, d), l, s in itertools.product(grid["window_ms"], grid["features"], grid["forest"],
                                                         grid["links"], grid["lesson_s"])]


def post_settings(grid=GRID) -> List[dict]:
    return [{"smooth": list(sm), "moving_run": m, "unsure_p": u}
            for sm, m, u in itertools.product(grid["smooth"], grid["moving_run"], grid["unsure_p"])]


def variant_key(v: dict) -> str:
    return json.dumps({k: v[k] for k in DEFAULTS}, sort_keys=True)


# --- loading and checks ----------------------------------------------------------------------

class Refused(Exception):
    """The sweep will not do this. The message says why and what to do instead."""


def content_hash(messages: List[dict]) -> str:
    """A session's identity: its readings and labels, whatever its file name or meta say."""
    h = hashlib.sha256()
    for m in sorted((m for m in messages if m.get("type") in ("rssi", "label")),
                    key=lambda m: (m.get("recv_t"), m.get("type"), m.get("link", ""))):
        body = {k: v for k, v in m.items() if k not in ("seq", "src")}
        h.update(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())
    return h.hexdigest()


def scrub_findings(path: Path) -> int:
    """How many identifiers sim/scrub.py would remove from this file (0 = nothing to scrub)."""
    from sim.scrub import scrub
    with open(path, encoding="utf-8") as f:
        return sum(len(found) for _, found in scrub(f))


def _baseline_history(folder: Path) -> List[dict]:
    """Every baseline, oldest first: baselines.jsonl (PR #469 keeps one line per baseline), else
    the single baseline.json the brain writes on main."""
    out = []
    log = folder / "baselines.jsonl"
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
                out.append({"t": e["t"], "base": {k: float(v) for k, v in e["base"].items()}})
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
    elif (folder / "baseline.json").exists():
        doc = json.loads((folder / "baseline.json").read_text(encoding="utf-8"))
        out.append({"t": doc.get("t") or 0,
                    "base": {k: float(v["base_dbm"]) for k, v in doc["links"].items() if v.get("base_dbm") is not None}})
    return sorted(out, key=lambda e: e["t"])


def _desks(history: List[dict]) -> List[int]:
    """A desk number per baseline. A baseline that keeps every link within DRIFT_DB of the one
    before is the same desk (an automatic re-baseline); one that moves a link further is a new desk."""
    desks, desk = [], -1
    for i, e in enumerate(history):
        prev = history[i - 1]["base"] if i else None
        same = prev is not None and set(prev) == set(e["base"]) and \
            all(abs(prev[k] - e["base"][k]) <= DRIFT_DB for k in prev)
        desk = desk if same else desk + 1
        desks.append(desk)
    return desks


def load_layout(folder: Path, nodes: Optional[Path] = None) -> dict:
    """The layout the sessions were recorded on: --nodes, else <folder>/nodes.json, else radio/nodes.json."""
    for p in (nodes, folder / "nodes.json", REPO / "radio" / "nodes.json"):
        if p and Path(p).exists():
            return json.loads(Path(p).read_text(encoding="utf-8"))
    raise Refused("no nodes.json for the layout")


def load_folder(folder, scrubbed: bool = False, nodes=None) -> dict:
    """Every session in a folder of bus recordings, checked before anything is uploaded.

    Refuses a file that still holds identifiers (sim/scrub.py --check would fail), and real
    recordings without --scrubbed: the scrub tool leaves no mark in a file, and the bus already
    writes the same compact JSON it does, so a scrubbed file can't be told from an unscrubbed one
    that happens to hold no identifiers. The flag is the operator saying the tool was run.
    Simulated and real sessions are never mixed in one sweep.
    """
    from brain.core import last_meta, read_session
    folder = Path(folder)
    if not folder.is_dir():
        raise Refused(f"{folder} is not a folder")
    history = _baseline_history(folder)
    if not history:
        raise Refused(f"no baseline.json or baselines.jsonl in {folder}: copy the board's data/sessions/"
                      "baseline.json (and baselines.jsonl if it exists) next to the recordings")
    desk_of = _desks(history)
    sessions, dirty, srcs = [], [], set()
    for path in sorted(folder.glob("*.jsonl")):
        if path.name == "baselines.jsonl":
            continue
        found = scrub_findings(path)
        if found:
            dirty.append(f"{path.name} ({found} identifiers)")
            continue
        meta = last_meta(path)
        if not meta or not meta.get("session"):
            continue
        msgs = read_session(path, meta.get("recv_t"))
        if not msgs:
            continue
        src = {m.get("src") for m in msgs}
        srcs |= src
        t = meta.get("recv_t", msgs[0]["recv_t"])
        idx = max([i for i, e in enumerate(history) if e["t"] <= t] or [0])
        sessions.append({"id": str(meta["session"]), "file": path.name, "purpose": meta.get("purpose"),
                         "walker": meta.get("walker"), "desk": desk_of[idx], "base": history[idx]["base"],
                         "messages": msgs, "hash": content_hash(msgs), "src": sorted(s for s in src if s)})
    if dirty:
        raise Refused("these files still hold device identifiers; run python -m sim.scrub <file> <clean copy> "
                      "on each and sweep the clean copies: " + ", ".join(dirty))
    live = bool(srcs - {"sim"})
    if live and srcs & {"sim"}:
        raise Refused("this folder mixes simulated and real sessions; sweep them separately")
    if live and not scrubbed:
        raise Refused("these are real recordings. Run python -m sim.scrub on every file first, then pass "
                      "--scrubbed to say you did (a scrubbed file carries no mark the sweep can check)")
    ids = [s["id"] for s in sessions]
    if len(ids) != len(set(ids)):
        raise Refused("two files hold the same session id")
    return {"sessions": sessions, "layout": load_layout(folder, nodes),
            "label": "from recordings" if live else "simulated", "folder": str(folder)}


# --- the seal --------------------------------------------------------------------------------

class Ledger:
    """sweep-out/sealed.json: every held-out session ever seen, by hash, and whether it was scored."""

    def __init__(self, path):
        self.path = Path(path)
        self.doc = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def seal(self, session: dict, now: str) -> None:
        self.doc.setdefault(session["hash"], {"session": session["id"], "file": session["file"],
                                              "sealed_at": now, "scored_at": None})

    def sealed(self, h: str) -> bool:
        return h in self.doc

    def scored(self, h: str) -> bool:
        return bool(self.doc.get(h, {}).get("scored_at"))

    def mark_scored(self, h: str, now: str) -> None:
        self.doc[h]["scored_at"] = now

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")


class Sealed:
    """The held-out sessions. Their readings are handed out once, with the chosen setting."""

    def __init__(self, sessions: List[dict]):
        self._sessions = sessions
        self.hashes = {s["hash"] for s in sessions}
        self.ids = [s["id"] for s in sessions]
        self.spent = False

    def __len__(self):
        return len(self._sessions)

    def open(self, chosen: dict) -> List[dict]:
        if self.spent:
            raise Refused("the held-out sessions were already scored once in this run")
        if not chosen:
            raise Refused("the held-out sessions open only for a chosen setting")
        self.spent = True
        return list(self._sessions)


def split(data: dict, ledger: Ledger, now: str) -> tuple:
    """(tuning sessions, Sealed). Held-out sessions are sealed in the ledger first; any session
    whose readings match a sealed hash is refused, whatever its purpose says now."""
    from brain.core import TRAIN_PURPOSES
    for s in data["sessions"]:
        if s["purpose"] == "heldout":
            ledger.seal(s, now)
    tune, fresh, spent = [], [], []
    for s in data["sessions"]:
        if s["purpose"] == "heldout":
            (spent if ledger.scored(s["hash"]) else fresh).append(s)
        elif s["purpose"] in TRAIN_PURPOSES:
            if ledger.sealed(s["hash"]):
                raise Refused(f"{s['file']} has the same readings as sealed held-out session "
                              f"{ledger.doc[s['hash']]['session']}; it can never be used for tuning")
            tune.append(s)
    assert_tunable(tune, ledger)
    return tune, Sealed(fresh), spent


def assert_tunable(sessions: List[dict], ledger: Optional[Ledger] = None, sealed: Optional[set] = None) -> None:
    """Every tuning path calls this first."""
    from brain.core import TRAIN_PURPOSES
    for s in sessions:
        if s.get("purpose") not in TRAIN_PURPOSES:
            raise Refused(f"session {s.get('id')} has purpose {s.get('purpose')}: tuning reads train and object only")
        if (ledger and ledger.sealed(s["hash"])) or (sealed and s["hash"] in sealed):
            raise Refused(f"session {s.get('id')} is sealed held-out data")


def readiness(tune: List[dict], sealed: Sealed, spent: List[dict]) -> dict:
    """Can a winner be picked, and what should be recorded next."""
    walkers = sorted({s["walker"] for s in tune if s["walker"]})
    empty = [s for s in tune if not s["walker"]]
    desks = sorted({s["desk"] for s in tune})
    todo = []
    if len(walkers) < 3:
        todo.append(f"{3 - len(walkers)} more people walking a train recording each (about 60 s: step left, "
                    "right, stand still 10 s, leave), so every person can be tested on a model that never saw them")
    if not empty:
        todo.append("one 30 s train recording of the empty strip, camera on, nobody in frame")
    if len(sealed) == 0:
        todo.append("one heldout recording by a person who is in no train recording" +
                    (" (every held-out session here was already scored once)" if spent else ""))
    if len(desks) < 2:
        todo.append("later, if there is time: the same layout set down at a second desk, a new baseline, and two "
                    "train recordings there, for the leave-one-desk-out check")
    ok = len(tune) >= MIN_TRAIN_SESSIONS and len(walkers) >= MIN_WALKERS
    why = None if ok else (f"{len(tune)} training sessions and {len(walkers)} walkers; a winner needs at least "
                           f"{MIN_TRAIN_SESSIONS} sessions and {MIN_WALKERS} walkers")
    return {"ok": ok, "why": why, "record_next": todo, "walkers": walkers, "desks": desks,
            "train_sessions": len(tune), "heldout_fresh": len(sealed), "heldout_spent": len(spent)}


# --- link subsets ----------------------------------------------------------------------------

def _crosses(a, b, w, h, steps=50) -> bool:
    """True when the straight line a-b runs through the inside of the w x h area people stand in."""
    for i in range(1, steps):
        f = i / steps
        x, y = a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])
        if 0.02 < x < w - 0.02 and 0.02 < y < h - 0.02:
            return True
    return False


def link_subsets(layout: dict) -> List[dict]:
    """all; strip_crossing (links whose line runs through the strip people stand in); the links of
    four nodes; router plus one receiver. The last three are the rows of PR #487's device table
    (proof/ablation.py), taken from there once it is merged, so the two tables line up."""
    nodes = {n["id"]: n["xyz_m"][:2] for n in layout["nodes"]}
    links = [l for l in layout["links"]]
    frame = layout.get("frame") or {}
    w, h = frame.get("strip_m") or frame.get("size_m") or (2.0, 2.0)
    rows = [{"name": "all", "nodes": list(nodes), "links": [l["id"] for l in links]},
            {"name": "strip_crossing", "nodes": list(nodes),
             "links": [l["id"] for l in links if _crosses(nodes[l["tx"]], nodes[l["rx"]], w, h)]}]
    try:
        from proof.ablation import subsets as device_rows   # PR #487
        for name, ids, ls in device_rows(layout)[1:]:
            rows.append({"name": name, "nodes": list(ids), "links": list(ls)})
    except ImportError:
        router = next(n["id"] for n in layout["nodes"] if "router" in n.get("roles", []))
        rx = next(n["id"] for n in layout["nodes"] if "receiver" in n.get("roles", []) and n["id"] != router)
        pair = [router, rx]
        four = (pair + [n for n in nodes if n not in pair])[:4]
        for name, ids in (("four_nodes", four if len(four) == 4 else []), ("router_receiver", pair)):
            rows.append({"name": name, "nodes": ids,
                         "links": [l["id"] for l in links if l["tx"] in ids and l["rx"] in ids]})
    return rows


# --- payloads (what goes to Modal) -----------------------------------------------------------

def payload(sessions: List[dict], layout: dict, sealed: Optional[set] = None) -> bytes:
    """The tuning sessions, packed small. Refuses anything sealed."""
    assert_tunable(sessions, sealed=sealed)
    return _pack(sessions, layout)


def _pack(sessions, layout) -> bytes:
    link_ids = [l["id"] for l in layout["links"]]
    li = {k: i for i, k in enumerate(link_ids)}
    out = []
    for s in sessions:
        rssi = [m for m in s["messages"] if m["type"] == "rssi" and m.get("link") in li]
        labels = [{k: m.get(k) for k in ("recv_t", "present", "zone", "motion", "mode", "persons_in_frame", "clipped")}
                  for m in s["messages"] if m["type"] == "label"]
        out.append({"id": s["id"], "walker": s["walker"], "desk": s["desk"], "purpose": s["purpose"],
                    "hash": s["hash"], "base": s["base"],
                    "rssi": [[m["recv_t"] for m in rssi], [li[m["link"]] for m in rssi], [m["dbm"] for m in rssi]],
                    "labels": labels})
    return gzip.compress(json.dumps({"links": link_ids, "subsets": link_subsets(layout),
                                     "zones": [z["id"] for z in layout["zones"]], "sessions": out}).encode(), mtime=0)


def unpack(blob: bytes) -> dict:
    doc = json.loads(gzip.decompress(blob))
    links = doc["links"]
    for s in doc["sessions"]:
        msgs = [{"type": "rssi", "recv_t": t, "link": links[i], "dbm": d} for t, i, d in zip(*s.pop("rssi"))]
        msgs += [dict(lb, type="label") for lb in s.pop("labels")]
        msgs.sort(key=lambda m: m["recv_t"])
        s["messages"] = msgs
    return doc


def sealed_payload(sealed: Sealed, chosen: dict, layout: dict) -> bytes:
    return _pack(sealed.open(chosen), layout)


# --- features, windows and models (this part runs in the containers) -------------------------

MAIN_STATS = ("mean", "std", "min", "max", "drop_db")
REL_STATS = ("drop_db", "std", "drop_min_db", "drop_max_db")


def _absolute(window, links):
    out = []
    for link in links:
        s = window["links"].get(link) or {"n": 0}
        if s["n"] == 0:
            base = window["base"].get(link, 0.0)
            out += [base, 0.0, base, base, 0.0]
        else:
            out += [s["mean"], s["std"], s["min"], s["max"], s["drop_db"] or 0.0]
    return out


def _relative(window, links):
    out = []
    for link in links:
        s = window["links"].get(link) or {"n": 0}
        base = window["base"].get(link)
        if s["n"] == 0 or base is None:
            out += [0.0, 0.0, 0.0, 0.0]
        else:
            out += [base - s["mean"], s["std"], base - s["max"], base - s["min"]]
    return out


def vector(window: dict, links, mode: str) -> List[float]:
    """brain.features.vector when the brain computes this mode; else the other mode's vector,
    as main (absolute) or PR #469 (relative) computes it, so both can be swept either side of
    that merge."""
    from brain import features as F
    if (mode == "absolute" and tuple(F.STATS) == MAIN_STATS) or (mode == "relative" and tuple(F.STATS) == REL_STATS):
        return F.vector(window, links=links)
    return (_absolute if mode == "absolute" else _relative)(window, links)


@contextmanager
def patched(module, **values):
    """Set a brain module's constants for one variant, and put them back."""
    old = {k: getattr(module, k) for k in values}
    for k, v in values.items():
        setattr(module, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(module, k, v)


def session_windows(s: dict, links: List[str], window_ms: int) -> List[dict]:
    """brain.features.windows for one session, against the baseline it was recorded on."""
    from brain import features as F
    with patched(F, WINDOW_MS=window_ms):
        return list(F.windows(s["messages"], s["base"], links=links))


def prepare(s: dict, wins: List[dict], links: List[str], mode: str) -> dict:
    """Arrays for one session: features, truth, what training may use."""
    import numpy as np
    from brain import train as T
    t0 = s["messages"][0]["recv_t"] if s["messages"] else 0
    X, end, zone, motion, use, truth = [], [], [], [], [], []
    for w in wins:
        lb = w["label"]
        X.append(vector(w, links, mode))
        end.append(w["end"])
        ok = lb is not None and lb["persons_in_frame"] <= 1   # two people in frame: the camera can't say who
        truth.append(lb["zone"] if ok else -1)
        motion.append((lb["motion"] or "") if ok else "")
        use.append(bool(ok and T.kind_of(w) is not None))
        zone.append(lb["zone"] if ok else -1)
    return {"X": np.asarray(X, float).reshape(len(wins), -1), "end": np.asarray(end), "t0": t0,
            "zone": np.asarray(zone), "motion": np.asarray(motion), "use": np.asarray(use, bool),
            "truth": np.asarray(truth), "start": np.asarray([w["start"] for w in wins])}


def fit(train: List[dict], trees: int, depth: int, lesson_s=None, n_jobs: int = 2):
    """The brain's zone and motion forests (brain/train.py's FOREST, with this size), on the
    training sessions; a walker's session is cut to its first lesson_s seconds."""
    import numpy as np
    from sklearn.ensemble import RandomForestClassifier
    from brain import train as T
    Xs, zs, ms = [], [], []
    for p in train:
        keep = p["use"].copy()
        if lesson_s is not None and p.get("walker"):
            keep &= p["end"] <= p["t0"] + lesson_s * 1000
        Xs.append(p["X"][keep]); zs.append(p["zone"][keep]); ms.append(p["motion"][keep])
    X, z, mo = np.concatenate(Xs), np.concatenate(zs), np.concatenate(ms)
    if len(X) == 0 or len(set(z.tolist())) < 2:
        return None
    cfg = dict(T.FOREST, n_estimators=trees, max_depth=depth, n_jobs=n_jobs)
    zf = RandomForestClassifier(**cfg).fit(X, z)
    pres = (z != 0) & np.isin(mo, ["moving", "still"])
    mf = RandomForestClassifier(**cfg).fit(X[pres], mo[pres]) if len(set(mo[pres].tolist())) >= 2 else None
    return {"zone": zf, "motion": mf, "fixed_motion": (mo[pres][0] if pres.any() else None), "windows": len(X)}


def predict(model, p: dict) -> dict:
    import numpy as np
    from brain import train as T
    probs = np.zeros((len(p["X"]), len(T.ZONES)))
    if len(p["X"]):
        pr = model["zone"].predict_proba(p["X"])
        for j, c in enumerate(model["zone"].classes_):
            probs[:, T.ZONES.index(int(c))] = pr[:, j]
    zone = probs.argmax(axis=1)
    if model["motion"] is not None and len(p["X"]):
        motion = model["motion"].predict(p["X"])
    else:
        motion = np.asarray([model["fixed_motion"] or "still"] * len(p["X"]))
    return {"zone": zone, "top": probs.max(axis=1), "motion": motion, "zones": [z for z in T.ZONES[1:] if probs[:, z].any()]}


def score_session(p: dict, pred: dict, post: dict, zones: List[int]) -> List[float]:
    """[credit, labelled windows, still-timer error sum (s), windows with a person, raw correct].

    credit is the decision's zone against the camera's (a "not sure" answer earns UNSURE_CREDIT).
    The decisions also go through brain/alert.py's Watch, with this variant's smoothing and still
    timer, exactly as the live loop feeds it (one decision per 0.1 s window); the still-timer error
    is how far its still_s is from the camera's own count of still time in the same zone."""
    from brain import alert as A
    n_dec, need = post["smooth"]
    credit = n = still_err = n_person = raw_ok = 0.0
    with patched(A, SMOOTH_DECISIONS=n_dec, SMOOTH_MAJORITY=need, MOVING_RUN=post["moving_run"]):
        watch = A.Watch(limits={}, led=A.NoLed())
        truth_still, truth_zone = 0, None
        for i in range(len(p["end"])):
            z = int(pred["zone"][i])
            present = z != 0
            unsure = present and post["unsure_p"] > 0 and float(pred["top"][i]) < post["unsure_p"]
            watch.on_pred(int(p["end"][i]), {"present": present, "kind": "person" if present else "none",
                                             "zone": z, "zone_set": list(zones) if unsure else ([z] if present else []),
                                             "motion": str(pred["motion"][i]) if present else None})
            tz = int(p["truth"][i])
            if tz < 0:
                truth_still, truth_zone = 0, None
                continue
            n += 1
            raw_ok += z == tz
            credit += UNSURE_CREDIT if unsure else float(z == tz)   # what pred.zone shows on the screen
            if tz != 0:
                still = p["motion"][i] == "still"
                truth_still = truth_still + 100 if still and truth_zone == tz else 0
                still_err += abs(watch.still_ms - truth_still) / 1000.0
                n_person += 1
            else:
                truth_still = 0
            truth_zone = tz
    return [credit, n, still_err, n_person, raw_ok]


def folds(sessions: List[dict]) -> Dict[str, List[tuple]]:
    """{"walker": [(train ids, test ids)], "desk": [...]} over the tuning sessions. Sessions with no
    walker (the empty strip, objects) always stay in training."""
    walkers = sorted({s["walker"] for s in sessions if s["walker"]})
    out = {"walker": [([s["id"] for s in sessions if s["walker"] != w],
                       [s["id"] for s in sessions if s["walker"] == w]) for w in walkers]}
    desks = sorted({s["desk"] for s in sessions})
    if len(desks) >= 2:
        out["desk"] = [([s["id"] for s in sessions if s["desk"] != d],
                        [s["id"] for s in sessions if s["desk"] == d and s["walker"]]) for d in desks]
    return out


def bootstrap(per_session: Dict[str, List[float]], col: int = 0) -> Optional[list]:
    """proof/score.py's session bootstrap (2000 rounds, 95%)."""
    from proof.score import cluster_interval
    return cluster_interval([(v[col], v[1]) for v in per_session.values()])


def summarize(per_session: Dict[str, List[float]]) -> dict:
    tot = [sum(v[i] for v in per_session.values()) for i in range(5)]
    score = tot[0] / tot[1] if tot[1] else None
    still = tot[2] / tot[3] if tot[3] else 0.0
    return {"score": score, "ci95": bootstrap(per_session), "zone_raw": tot[4] / tot[1] if tot[1] else None,
            "zone_ci95": bootstrap(per_session, col=4),
            "still_err_s": still, "windows": int(tot[1]), "raw_correct": int(tot[4]),
            "objective": None if score is None else score - STILL_WEIGHT * still}


_PREPARED: dict = {}


def run_job(blob: bytes, job: dict, posts: List[dict], n_jobs: int = 2, lesson_curve: bool = False) -> dict:
    """Every post setting for one model setting, on every fold. Runs in a container."""
    import time
    t_start = time.monotonic()
    doc = unpack(blob)
    sessions = doc["sessions"]
    assert_tunable(sessions)
    links = next(r["links"] for r in doc["subsets"] if r["name"] == job["links"])
    if not links:
        return {"job": job, "skipped": "no links in this subset", "variants": [], "seconds": 0.0}
    key = (hashlib.sha256(blob).hexdigest(), job["window_ms"], job["features"], tuple(links))
    if key not in _PREPARED:            # jobs that differ only in forest or lesson share the windows
        _PREPARED.clear()
        by_id = {}
        for s in sessions:
            p = prepare(s, session_windows(s, links, job["window_ms"]), links, job["features"])
            p["walker"], p["desk"], p["id"] = s["walker"], s["desk"], s["id"]
            by_id[s["id"]] = p
        _PREPARED[key] = by_id
    by_id = _PREPARED[key]
    results = {}       # (fold kind, post index) -> {session id: sums}
    fit_s = []
    for kind, fs in folds(sessions).items():
        for train_ids, test_ids in fs:
            t0 = time.monotonic()
            model = fit([by_id[i] for i in train_ids], job["trees"], job["depth"], job["lesson_s"], n_jobs)
            fit_s.append(time.monotonic() - t0)
            for sid in test_ids:
                p = by_id[sid]
                if model is None:
                    continue
                pred = predict(model, p)
                for k, post in enumerate(posts):
                    results.setdefault((kind, k), {})[sid] = score_session(p, pred, post, doc["zones"])
    variants = []
    for k, post in enumerate(posts):
        v = dict(job, **post)
        row = {"variant": v, "key": variant_key(v)}
        for kind in ("walker", "desk"):
            per = results.get((kind, k))
            if per:
                row[kind] = dict(summarize(per), per_session=per)
        objs = [row[kind]["objective"] for kind in ("walker", "desk") if kind in row and row[kind]["objective"] is not None]
        row["objective"] = sum(objs) / len(objs) if objs else None
        variants.append(row)
    curve = lesson_rows(sessions, by_id, job, n_jobs) if lesson_curve else []
    return {"job": job, "variants": variants, "lesson_curve": curve, "fit_s": fit_s,
            "seconds": time.monotonic() - t_start}


def lesson_rows(sessions, by_id, job, n_jobs) -> List[dict]:
    """The live lesson: the camera teaches on one person for L seconds (plus the empty-strip
    recordings at that desk), then the model is scored on the rest of that same recording."""
    import numpy as np
    post = {k: DEFAULTS[k] for k in ("smooth", "moving_run", "unsure_p")}
    rows = []
    for L in LESSON_CURVE_S:
        per = {}
        for s in sessions:
            if not s["walker"]:
                continue
            p = by_id[s["id"]]
            empties = [by_id[e["id"]] for e in sessions if not e["walker"] and e["desk"] == s["desk"]]
            cut = p["t0"] + L * 1000
            head = dict(p, walker=None, use=p["use"] & (p["end"] <= cut))
            tail_mask = p["start"] >= cut
            if tail_mask.sum() < 50:
                continue
            model = fit([head] + empties, job["trees"], job["depth"], None, n_jobs)
            if model is None:
                continue
            tail = {k: (v[tail_mask] if isinstance(v, np.ndarray) and len(v) == len(tail_mask) else v) for k, v in p.items()}
            per[s["id"]] = score_session(tail, predict(model, tail), post, [])
        if per:
            rows.append(dict(summarize(per), lesson_s=L, sessions=len(per), per_session=per))
    return rows


def score_heldout(train_blob: bytes, sealed_blob: bytes, settings: List[dict], n_jobs: int = 2) -> List[dict]:
    """The once-only held-out score: for each setting, train on every tuning session, score the sealed ones."""
    tdoc, hdoc = unpack(train_blob), unpack(sealed_blob)
    out = []
    for v in settings:
        links = next(r["links"] for r in tdoc["subsets"] if r["name"] == v["links"])
        prep = []
        for s in tdoc["sessions"]:
            p = prepare(s, session_windows(s, links, v["window_ms"]), links, v["features"])
            p["walker"] = s["walker"]
            prep.append(p)
        model = fit(prep, v["trees"], v["depth"], v["lesson_s"], n_jobs)
        per = {}
        for s in hdoc["sessions"]:
            p = prepare(s, session_windows(s, links, v["window_ms"]), links, v["features"])
            per[s["id"]] = score_session(p, predict(model, p), v, tdoc["zones"])
        out.append({"variant": v, **summarize(per), "per_session": per})
    return out


def paired_gain(a: Dict[str, List[float]], b: Dict[str, List[float]]) -> dict:
    """a minus b on the same sessions, with a session-bootstrap interval of the difference."""
    from proof.score import cluster_interval
    common = sorted(set(a) & set(b))
    pairs = []
    for sid in common:
        sa = a[sid][0] / a[sid][1] if a[sid][1] else 0.0
        sb = b[sid][0] / b[sid][1] if b[sid][1] else 0.0
        pairs.append(((sa - sb) * b[sid][1], b[sid][1]))
    tot = sum(n for _, n in pairs)
    return {"gain": (sum(c for c, _ in pairs) / tot) if tot else None, "ci95": cluster_interval(pairs),
            "sessions": len(common)}


def pick(rows: List[dict]) -> Optional[dict]:
    """The best objective; ties go to the smaller forest, then the shorter lesson (cheaper on the board)."""
    ok = [r for r in rows if r.get("objective") is not None]
    if not ok:
        return None
    return max(ok, key=lambda r: (round(r["objective"], 4), -r["variant"]["trees"], -(r["variant"]["lesson_s"] or 999)))


def fmt_ci(ci) -> str:
    return "n/a" if not ci else f"{ci[0]:.1%} to {ci[1]:.1%}"
