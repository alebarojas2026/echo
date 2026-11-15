"""Play recordings of the one-spot layout through the brain and score what it said.

For choosing the presence line's numbers ("presence" and "armed" in the layout file, and a few
of brain/settings.py) from recordings instead of from a guess. The readings go through
brain.core.Brain itself: its windows, the presence line's on and off levels, the drift follow,
moving / still from the line's spread, armed mode. Nothing of the rules is written again here.

What a human gives it is a folder of scrubbed session files and a plan (a JSON file kept beside
the recordings, never in the repo):

    {"runs": [{"id": "main",
               "sessions": [{"session": "s1", "is": "baseline", "set": "tune"},
                            {"session": "s2", "is": "person",   "set": "tune"},
                            {"session": "s3", "is": "empty",    "set": "heldout"}]}]}

A run is one sitting of the kit: its sessions are played in order through one brain. "is" says
what was done while the session was recorded: baseline (empty; the empty level is taken from
it), empty, person (standing on the spot), still, moving, walk (walking straight through, with
"passes": how many), side (walking past beside the line), behind (standing behind the far
device), thing (something left in the line). A run whose first session is not "baseline" names
"baseline_s": that many seconds from the start of its first session are the baseline. A run
plays on radio/layouts/gate.json unless it names another file there ("layout": "gate-3").

Two things are not as on the board, and every number from here carries them:
- The recordings are separate files with a few seconds between them that nobody recorded.
  They are joined end to end, so a person "appears" between one reading and the next. The
  time to find and to let go measured at a join is the rules' own delay and leaves out the
  second or so a body takes to step in. Real arrivals are only in the "walk" sessions. For
  the same reason moving / still is scored from 3 s into a session: until then the spread
  it is read from still holds the jump at the join.
- These recordings carry no camera labels, so no model can be fit. A stand-in that always
  answers "nobody, no object" goes through brain.train.Model.predict unchanged: the presence
  line decides, as it does on the board. What a taught model adds there (calling a thing an
  object, a learned moving / still boundary) is not in these numbers.

The wall between choosing and reporting: load(..., which="tune") never opens a session marked
"heldout", and a run with nothing to tune on is left out whole. which="heldout" plays every
session of a run (the brain has to live through the evening in order) and scores only the
held-out ones.

    python -m lab.gate_tune <folder> <plan.json> --which tune --set on_db=8 --set off_db=4

prints one JSON object. It writes nothing. These are counts from recordings for a person to
read; they are not PROOF.md results.
"""
from __future__ import annotations

import argparse
import json
import statistics
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from brain import features as F
from brain import settings as S
from brain.alert import Armed
from brain.core import Brain
from brain.train import Model

LAYOUTS = Path(__file__).resolve().parents[1] / "radio" / "layouts"
LAYOUT = "gate"               # a run plays on this layout file unless the plan gives it another ("layout": "gate-3")
STATE_EVERY_MS = 100          # the live loop takes state about 10 times a second
JOIN_MS = 40                  # the next file starts this long after the last reading of the one before
THERE = ("person", "still", "moving")          # somebody stands on the spot for the whole session
NOBODY = ("empty", "side", "behind")           # nobody is on the spot at any time
KINDS = ("baseline",) + THERE + NOBODY + ("walk", "thing")
HOLDS = (2.0, 2.5, 3.0, 3.5, 4.0)              # armed.hold_s values scored side by side
MOTION_SKIP_MS = 3000         # moving / still is not scored this long into a session: the spread still holds the join
PASS_DB = 3.0                 # a walk-through, read off the raw line: readings this far under the session's own level
PASS_GAP_MS = 1000            # ... and it is over once the line has been back up for this long

# What a variant may change, with what the layout file and the brain have today.
DEFAULTS = {"on_db": 7.0, "off_db": 4.0, "window_ms": 1000, "zone_hold": 5, "drift_follow_s": 30,
            "moving_spread_db": 2.0, "spread_ms": 2000}


def read_rssi(path) -> List[tuple]:
    """(recv_t, link, dbm) of a session file's readings, oldest first."""
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if '"rssi"' not in line:
                continue
            m = json.loads(line)
            if m.get("type") == "rssi" and m.get("recv_t") is not None:
                out.append((int(m["recv_t"]), m["link"], float(m["dbm"])))
    out.sort(key=lambda r: r[0])
    return out


def load(folder, plan: dict, which: str) -> List[dict]:
    """The plan's runs, read and joined end to end: [{"id", "base": [...], "readings": [...],
    "parts": [{"session", "is", "set", "start", "end", "scored", ...}]}].

    which="tune": only sessions marked "tune" are opened. which="heldout": every session of a
    run that has a held-out one is played, and only the held-out ones are scored."""
    if which not in ("tune", "heldout"):
        raise ValueError('which is "tune" or "heldout"')
    folder, runs = Path(folder), []
    for run in plan["runs"]:
        sessions = [s for s in run["sessions"] if which == "heldout" or s["set"] == "tune"]
        for s in run["sessions"]:
            if s["is"] not in KINDS or s["set"] not in ("tune", "heldout"):
                raise ValueError(f'{s["session"]}: "is" is one of {", ".join(KINDS)} and "set" is tune or heldout')
        if not any(s["set"] == which and s["is"] != "baseline" for s in sessions):
            continue
        first = run["sessions"][0]
        if which == "tune" and first["set"] != "tune":
            raise ValueError(f'run {run["id"]}: its baseline is a held-out session, so nothing of it can be tuned on')
        if first["is"] != "baseline" and not run.get("baseline_s"):
            raise ValueError(f'run {run["id"]}: the first session is the baseline, or the run names baseline_s')
        out = {"id": run["id"], "layout": run.get("layout", LAYOUT), "base": [], "readings": [], "parts": []}
        cursor = 0
        for i, s in enumerate(sessions):
            raw = read_rssi(folder / f'{s["session"]}.jsonl')
            if not raw:
                raise ValueError(f'{s["session"]}: no readings')
            shift = cursor - raw[0][0]
            rows = [(t + shift, link, dbm) for t, link, dbm in raw]
            start, cursor = rows[0][0], rows[-1][0] + JOIN_MS
            if i == 0:
                cut = start + int(run["baseline_s"] * 1000) if s["is"] != "baseline" else cursor
                out["base"] = [r for r in rows if r[0] < cut]
                if s["is"] != "baseline":
                    start = cut
            out["readings"] += rows
            out["parts"].append({**s, "start": start, "end": cursor,
                                 "scored": s["set"] == which and s["is"] != "baseline"})
        runs.append(out)
    return runs


def baseline_doc(base: List[tuple]) -> dict:
    """baseline.json as the brain writes it, from the readings of an empty stretch."""
    msgs = [{"type": "rssi", "recv_t": t, "link": link, "dbm": dbm} for t, link, dbm in base]
    level, quiet = F.baseline(msgs), F.quiet(msgs)
    seconds = max((base[-1][0] - base[0][0]) / 1000, 1.0)
    count: Dict[str, int] = {}
    for _, link, _ in base:
        count[link] = count.get(link, 0) + 1
    return {"t": base[-1][0], "session": None,
            "links": {k: {"base_dbm": level[k], "expected_hz": round(count[k] / seconds, 1),
                          **({"quiet_db": round(quiet[k], 2)} if k in quiet else {})} for k in level}}


class _Never:
    """Stands where a forest would: one class, always."""

    def __init__(self, answer):
        self.classes_ = [answer]
        self.estimators_ = []

    def predict_proba(self, x):
        return [[1.0] for _ in x]


def stand_in(brain: Brain) -> Model:
    """A model that was taught nothing: its zone forest says "nobody" and its kind forest "none",
    every window. Model.predict itself runs, so the presence line's word becomes the decision
    the same way it does with a taught model."""
    model = Model(brain.base, ver="stand-in", links=brain.model_links, zones=brain.zone_ids,
                  crossing=brain.crossing, motion_line=brain.presence_line)
    model.zone, model.kind = _Never(0), _Never("none")
    return model


def make_brain(folder, base: List[tuple], params: Optional[dict] = None, layout: str = LAYOUT) -> Brain:
    """A brain on a layout file of radio/layouts with the variant's numbers, the baseline of `base` and
    the stand-in model. Readings of lines the layout doesn't have are not part of the baseline."""
    p = {**DEFAULTS, **(params or {})}
    unknown = sorted(set(p) - set(DEFAULTS))
    if unknown:
        raise ValueError(f"not something a variant can change: {', '.join(unknown)}")
    nodes = json.loads((LAYOUTS / f"{layout}.json").read_text(encoding="utf-8"))
    known = {link["id"] for link in nodes["links"]}
    base = [r for r in base if r[1] in known]
    nodes["presence"] = {**nodes["presence"], "on_db": p["on_db"], "off_db": p["off_db"],
                         "moving_spread_db": p["moving_spread_db"]}
    folder = Path(folder)
    (folder / "baseline.json").write_text(json.dumps(baseline_doc(base)), encoding="utf-8")
    settings = S.DEFAULT.with_(zone_hold=int(p["zone_hold"]), drift_follow_s=int(p["drift_follow_s"]))
    brain = Brain(clock=None, sessions_dir=folder, settings=settings, nodes=nodes)
    if not brain.base or brain.presence_line is None:
        raise ValueError("the baseline has no readings of this layout's lines, or the layout names no presence line")
    brain.model = stand_in(brain)
    return brain


def play(run: dict, params: Optional[dict] = None, holds=HOLDS) -> dict:
    """One run through a new brain. Returns the states taken ten times a second as
    (t, present, motion, kind) with present None while the decision is hidden, the events with
    their times, what armed mode would have raised for each hold in `holds`, and the empty
    level the brain ended on."""
    p = {**DEFAULTS, **(params or {})}
    old = (F.WINDOW_MS, F.STEADY_MS)
    # The window lengths are the contract's (section 6) and are constants in brain/features.py.
    # A variant changes them for its own replay only, to show what another length would do.
    F.WINDOW_MS, F.STEADY_MS = int(p["window_ms"]), int(p["spread_ms"])
    try:
        with tempfile.TemporaryDirectory() as folder:
            brain = make_brain(folder, run["base"], p, run.get("layout", LAYOUT))
            line = brain.presence_line
            brain.on_cmd({"v": 2, "type": "cmd", "cmd": "arm", "args": {"on": True}})
            brain.pop_events()
            guards = {h: Armed(brain.settings, h) for h in holds}   # the brain's own rule, once per hold
            for g in guards.values():
                g.arm(True)
            raised: List[tuple] = []
            clock = [0]
            real = brain.armed.on_pred

            def on_pred(pred):
                for h, g in guards.items():
                    if g.on_pred(pred) is not None:
                        raised.append((clock[0], h, "intrusion"))
                    for _ in g.pop_passed():
                        raised.append((clock[0], h, "passed_by"))
                return real(pred)

            brain.armed.on_pred = on_pred
            rows, events, next_state = [], [], None
            for t, link, dbm in run["readings"]:
                clock[0] = t
                brain.on_message({"v": 2, "type": "rssi", "t": t, "recv_t": t, "link": link, "dbm": dbm})
                if next_state is None or t >= next_state:
                    next_state = t + STATE_EVERY_MS if next_state is None or t - next_state >= STATE_EVERY_MS \
                        else next_state + STATE_EVERY_MS
                    pred = brain.state()["pred"]
                    events += [(t, e["kind"]) for e in brain.pop_events()]
                    rows.append((t, None if pred is None else bool(pred["present"]),
                                 pred and pred.get("motion"), pred and pred.get("kind")))
            return {"rows": rows, "events": events, "armed": raised, "line": line,
                    "end_base": brain.base.get(line), "start_base": baseline_doc(run["base"])["links"][line]["base_dbm"]}
    finally:
        F.WINDOW_MS, F.STEADY_MS = old


def passes(readings: List[tuple], line: str, start: int, end: int) -> List[tuple]:
    """The walk-throughs of a session, read off the raw presence line: (first, last) times of each
    stretch of readings PASS_DB or more under the session's own median level, a stretch ending
    once the line has been back up for PASS_GAP_MS. One low reading alone is no pass."""
    pts = [(t, d) for t, link, d in readings if link == line and start <= t < end]
    if not pts:
        return []
    level = statistics.median(d for _, d in pts)
    out, first, last, n = [], None, None, 0
    for t, d in pts:
        if level - d >= PASS_DB:
            if first is None:
                first, n = t, 0
            last, n = t, n + 1
        elif first is not None and t - last >= PASS_GAP_MS:
            if n >= 2:
                out.append((first, last))
            first = None
    if first is not None and n >= 2:
        out.append((first, last))
    return out


def score(run: dict, played: dict, holds=HOLDS) -> List[dict]:
    """One row per scored session of a played run."""
    rows, out = played["rows"], []
    step = STATE_EVERY_MS / 1000
    for i, part in enumerate(run["parts"]):
        if not part["scored"]:
            continue
        a, b, kind = part["start"], part["end"], part["is"]
        mine = [r for r in rows if a <= r[0] < b]
        before = run["parts"][i - 1]["is"] if i else None
        row = {"run": run["id"], "session": part["session"], "is": kind, "seconds": round((b - a) / 1000, 1),
               "hidden_s": round(sum(1 for r in mine if r[1] is None) * step, 1)}
        enters = [t for t, k in played["events"] if k == "enter" and a <= t < b]
        if kind in NOBODY:
            free = a
            if before in THERE:   # the person of the session before has to be let go first
                gone = next((t for t, present, _, _ in mine if present is False), None)
                row["release_s"] = None if gone is None else round((gone - a) / 1000, 2)
                free = b if gone is None else gone
            after = [r for r in mine if r[0] >= free]
            row["empty_s"] = round(len(after) * step, 1)
            row["false_present_s"] = round(sum(1 for r in after if r[1]) * step, 1)
            row["false_enters"] = sum(1 for t in enters if t >= free)
            row["false_alarms"] = {str(h): sum(1 for t, hold, k in played["armed"] if hold == h and free <= t < b)
                                   for h in holds}
        elif kind in THERE:
            seen = next((t for t, present, _, _ in mine if present), None)
            row["found"] = seen is not None
            if before not in THERE:
                row["detect_s"] = None if seen is None else round((seen - a) / 1000, 2)
                said = next((t for t in enters), None)
                row["enter_s"] = None if said is None else round((said - a) / 1000, 2)
            after = [r for r in mine if seen is not None and r[0] >= seen]
            row["present_share"] = round(sum(1 for r in after if r[1]) / len(after), 3) if after else 0.0
            row["dropouts"] = sum(1 for x, y in zip(after, after[1:]) if x[1] and y[1] is False)
            there = [r for r in after if r[1] and r[0] >= a + MOTION_SKIP_MS]
            if kind in ("still", "moving"):
                row["motion_n"] = len(there)
                row["motion_right"] = sum(1 for r in there if r[2] == kind)
        elif kind == "walk":
            found, released, long_ = [], [], []
            real = passes(run["readings"], played["line"], a, b)
            for first, last in real:
                seen = next((t for t, present, _, _ in mine if present and first <= t <= last + 2000), None)
                found.append(None if seen is None else round((seen - first) / 1000, 2))
                gone = next((t for t, present, _, _ in mine if seen is not None and t > max(seen, last)
                             and present is False), None)
                released.append(None if gone is None else round((gone - last) / 1000, 2))
                long_.append(round((last - first) / 1000, 2))
            row.update(passes_said=part.get("passes"), passes_on_line=len(real), pass_s=long_,
                       detect_s=found, release_s=released, enters=len(enters),
                       present_s=round(sum(1 for r in mine if r[1]) * step, 1),
                       armed={str(h): {k: sum(1 for t, hold, what in played["armed"]
                                             if hold == h and what == k and a <= t < b)
                                       for k in ("passed_by", "intrusion")} for h in holds})
        else:   # a thing left in the line
            row["present_s"] = round(sum(1 for r in mine if r[1]) * step, 1)
            row["object_s"] = round(sum(1 for r in mine if r[3] == "object") * step, 1)
            row["enters"] = len(enters)
        out.append(row)
    return out


def total(rows: List[dict], holds=HOLDS) -> dict:
    """The scores of many sessions as one row, for comparing variants."""
    def vals(key, kinds):
        return [r[key] for r in rows if r["is"] in kinds and key in r]

    def mid(v):
        v = [x for x in v if x is not None]
        return None if not v else round(statistics.median(v), 2)

    def top(v):
        v = [x for x in v if x is not None]
        return None if not v else round(max(v), 2)

    people = [r for r in rows if r["is"] in THERE]
    detect, release = vals("detect_s", THERE), vals("release_s", NOBODY)
    out = {
        "empty_s": round(sum(vals("empty_s", NOBODY)), 1),
        "false_present_s": round(sum(vals("false_present_s", NOBODY)), 1),
        "false_enters": sum(vals("false_enters", NOBODY)),
        "false_alarms": {str(h): sum(r["false_alarms"][str(h)] for r in rows if r["is"] in NOBODY) for h in holds},
        "people": len(people), "found": sum(1 for r in people if r["found"]),
        "dropouts_standing": sum(r["dropouts"] for r in people if r["is"] != "moving"),
        "dropouts_moving": sum(r["dropouts"] for r in people if r["is"] == "moving"),
        "present_share_min": min((r["present_share"] for r in people if r["is"] != "moving"), default=None),
        "detect_s": mid(detect), "detect_s_max": top(detect), "not_found": sum(1 for x in detect if x is None),
        "enter_s": mid(vals("enter_s", THERE)),
        "release_s": mid(release), "release_s_max": top(release), "not_released": sum(1 for x in release if x is None),
        "hidden_s": round(sum(r["hidden_s"] for r in rows), 1),
    }
    for kind in ("still", "moving"):
        n, right = sum(vals("motion_n", (kind,))), sum(vals("motion_right", (kind,)))
        out[f"{kind}_right"] = None if not n else round(right / n, 3)
    walks = [r for r in rows if r["is"] == "walk"]
    if walks:
        out["walk"] = {
            "passes": sum(r["passes_said"] or r["passes_on_line"] for r in walks),
            "on_line": sum(r["passes_on_line"] for r in walks),
            "seen": sum(1 for r in walks for x in r["detect_s"] if x is not None),
            "detect_s": mid([x for r in walks for x in r["detect_s"]]),
            "detect_s_max": top([x for r in walks for x in r["detect_s"]]),
            "release_s": mid([x for r in walks for x in r["release_s"]]),
            "release_s_max": top([x for r in walks for x in r["release_s"]]),
            "armed": {str(h): {k: sum(r["armed"][str(h)][k] for r in walks) for k in ("passed_by", "intrusion")}
                      for h in holds},
        }
    things = [r for r in rows if r["is"] == "thing"]
    if things:
        out["thing"] = {"present_s": sum(r["present_s"] for r in things), "object_s": sum(r["object_s"] for r in things)}
    return out


def run_variant(runs: List[dict], params: Optional[dict] = None, holds=HOLDS, detail: bool = False) -> dict:
    """Every run through its own new brain with one variant's numbers. Returns the total, and each
    session's row too when detail is asked for."""
    rows, drift = [], {}
    for run in runs:
        played = play(run, params, holds)
        rows += score(run, played, holds)
        drift[run["id"]] = None if played["end_base"] is None else round(played["end_base"] - played["start_base"], 2)
    out = {"params": {**DEFAULTS, **(params or {})}, "total": total(rows, holds), "base_moved_db": drift}
    if detail:
        out["sessions"] = rows
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Play one-spot recordings through the brain and score what it said.")
    ap.add_argument("folder", help="the folder with the scrubbed session files")
    ap.add_argument("plan", help="the JSON file that says what each session is and which set it is in")
    ap.add_argument("--which", choices=("tune", "heldout"), default="tune")
    ap.add_argument("--set", action="append", default=[], metavar="NAME=VALUE",
                    help=f"change one of {', '.join(DEFAULTS)}")
    ap.add_argument("--detail", action="store_true", help="one row per session as well")
    args = ap.parse_args(argv)
    params = {}
    for pair in args.set:
        name, sep, value = pair.partition("=")
        if not sep or name not in DEFAULTS:
            raise SystemExit(f"--set wants name=value with a name from: {', '.join(DEFAULTS)}")
        params[name] = type(DEFAULTS[name])(value)
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    print(json.dumps(run_variant(load(args.folder, plan, args.which), params, detail=args.detail), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
