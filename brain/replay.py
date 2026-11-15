"""Play a recording through the brain's real decision code and count what it would have said.

    python -m brain.replay data/sessions/crowd1.jsonl --sessions data/sessions --armed
    python -m brain.replay data/sessions/crowd1.jsonl --sessions data/sessions --armed --hold-s 4
    python -m brain.replay data/sessions/crowd1.jsonl --sessions data/sessions --set moving_run=8
    python -m brain.replay crowd1.jsonl --sessions data/sessions --train walk1 walk2 empty1

For choosing the people rules' numbers (brain/settings.py) from a recording instead of from a
guess: how many intrusions an armed desk would have raised while people only walked past, how
many no-movement alerts fired, and how often a still timer was put back to zero.

The recording is a session file as the bus writes it (rssi and label lines with recv_t). The
readings go through brain.core.Brain itself: windows, the model, link health, the alert, armed
mode. Nothing is re-implemented here. Time follows the recording, so a ten minute file plays in
seconds.

The brain needs a baseline and a model:
- --sessions names the folder with baseline.json and model.pkl (data/sessions on the board).
  It is copied to a temporary folder first; nothing in it is written or changed.
- --train names recordings in that folder to fit a model from, instead of model.pkl (needed
  to try motion_links, which takes effect when a model is fit).

--armed arms before the first reading. --hold-s tries another armed.hold_s than nodes.json has.
--set name=value changes a setting for this run, any number of times. It prints one JSON object; nothing is written anywhere, and a person decides.
The counts say what the rules do with this recording. They are not accuracy numbers.
"""
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from typing import Iterable, List, Optional

from brain import settings as S
from brain.core import NODES_JSON, Brain, base_at, last_meta, read_session
from brain.train import Model

STATE_EVERY_MS = 100   # the live loop takes state about 10 times a second
COUNTED = ("intrusion", "passed_by", "alert_on", "alert_off", "enter", "exit", "zone_change", "checkin", "blind_on")


def replay(brain: Brain, messages: Iterable[dict], armed: bool = False) -> dict:
    """Feed messages (with recv_t, oldest first) to a brain that has a baseline and a model.
    Returns the counts. The brain is used as it is: arm it, or not, with `armed`."""
    # Armed mode is kept on disk now, so a brain on a work folder used before may come up armed:
    # set it both ways, every run.
    brain.on_cmd({"v": 2, "type": "cmd", "cmd": "arm", "args": {"on": bool(armed)}})
    brain.pop_events()
    before = dict(brain.watch.resets)
    events: List[dict] = []
    first = last = next_state = None
    decisions = present = hidden = 0
    longest_still = 0.0
    for msg in messages:
        t = msg.get("recv_t")
        if t is None:
            continue
        first = t if first is None else first
        last = t
        brain.on_message(msg)
        if next_state is None or t >= next_state:
            # ten states a second on the recording's own clock, whatever the readings' rate
            next_state = t + STATE_EVERY_MS if next_state is None or t - next_state >= STATE_EVERY_MS                 else next_state + STATE_EVERY_MS
            state = brain.state()
            events += brain.pop_events()
            pred = state["pred"]
            decisions += 1
            hidden += pred is None
            present += bool(pred and pred["present"])
            longest_still = max(longest_still, state["alert"]["still_s"] or 0.0)
    events += brain.pop_events()
    kinds = [e["kind"] for e in events]
    resets = {why: n - before.get(why, 0) for why, n in brain.watch.resets.items()}
    return {
        "seconds": 0.0 if first is None else round((last - first) / 1000, 1),
        "states": decisions,
        "states_with_no_pred": hidden,               # blind, or no model: nothing was decided then
        "present_s": round(present * STATE_EVERY_MS / 1000, 1),
        "intrusions": kinds.count("intrusion"),
        "passed_by": kinds.count("passed_by"),       # appeared while armed, gone before armed.hold_s
        "alerts": kinds.count("alert_on"),
        "still_timer_resets": resets,                # a timer that had started, put back to zero
        "longest_still_s": round(longest_still, 1),
        "events": {k: kinds.count(k) for k in COUNTED if k in kinds},
        "armed": armed,
        "hold_s": brain.armed.hold / S.DECISIONS_PER_S,
        "settings": brain.settings.as_dict(),
    }


def prepared(sessions_dir, settings: Optional[S.Settings] = None, train: Optional[List[str]] = None,
             folder=None, hold_s: Optional[float] = None) -> Brain:
    """A brain with the baseline and model of sessions_dir, working on a copy in `folder`.
    train: session names to fit a model from, instead of loading model.pkl.
    hold_s: another armed.hold_s than radio/nodes.json has, for this run."""
    nodes = json.loads(NODES_JSON.read_text(encoding="utf-8"))
    if hold_s is not None:
        nodes["armed"] = {**(nodes.get("armed") or {}), "hold_s": hold_s}
    src, folder = Path(sessions_dir), Path(folder)
    for name in ("baseline.json", "place.json", "baselines.jsonl") + (() if train else ("model.pkl",)):
        if (src / name).exists():
            shutil.copy(src / name, folder / name)
    brain = Brain(clock=None, sessions_dir=folder, settings=settings, nodes=nodes)
    if not brain.base:
        raise SystemExit(f"no baseline.json in {src}: the brain can't judge a recording without one")
    if train:
        history, sessions = brain._baselines(), []
        for name in train:
            path = src / (name if name.endswith(".jsonl") else f"{name}.jsonl")
            meta = last_meta(path)
            if meta is None:
                raise SystemExit(f"{path}: no recording with a meta line")
            sessions.append({"meta": meta, "messages": read_session(path, meta.get("recv_t")),
                             "base": base_at(history, meta.get("recv_t"))})
        brain.model = Model(brain.base, ver="replay", links=brain.model_links, zones=brain.zone_ids,
                            motion_links=brain.settings.motion_links, crossing=brain.crossing,
                            motion_line=brain.presence_line).fit(sessions)
    if brain.model is None:
        raise SystemExit(f"no model: {src} has no model.pkl for this baseline and layout; name recordings with --train")
    return brain


def parse_set(pairs: List[str]) -> dict:
    """["moving_run=8", "motion_links=a,b"] -> {"moving_run": 8, "motion_links": ["a", "b"]}."""
    out = {}
    for pair in pairs:
        name, sep, value = pair.partition("=")
        if not sep:
            raise SystemExit(f"--set wants name=value, got {pair!r}")
        if name == "motion_links":
            out[name] = None if value in ("", "null", "all") else [k for k in value.split(",") if k]
        else:
            try:
                out[name] = float(value) if name.endswith("_x_quiet") else int(value)
            except ValueError:
                raise SystemExit(f"--set {name}: {value!r} is not a {'number' if name.endswith('_x_quiet') else 'whole number'}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Play a recording through the brain and count intrusions, alerts and still-timer resets.")
    ap.add_argument("recording", help="a session file written by the bus (.jsonl)")
    ap.add_argument("--sessions", required=True, help="the folder with baseline.json and model.pkl (never written to)")
    ap.add_argument("--train", nargs="+", metavar="SESSION", help="fit the model from these recordings instead of model.pkl")
    ap.add_argument("--armed", action="store_true", help="arm before the first reading")
    ap.add_argument("--hold-s", type=float, metavar="SECONDS", help="another armed.hold_s than nodes.json has, for this run")
    ap.add_argument("--set", action="append", default=[], metavar="NAME=VALUE", help="change a setting for this run")
    args = ap.parse_args(argv)
    try:
        settings = S.load().with_(**parse_set(args.set))
    except ValueError as e:
        raise SystemExit(str(e))
    meta = last_meta(args.recording)
    messages = read_session(args.recording, meta.get("recv_t") if meta else None)
    with tempfile.TemporaryDirectory() as folder:
        brain = prepared(args.sessions, settings, args.train, folder, args.hold_s)
        counts = replay(brain, messages, armed=args.armed)
    counts["recording"] = {"file": Path(args.recording).name, "src": messages[0].get("src") if messages else None,
                           "purpose": (meta or {}).get("purpose")}
    print(json.dumps(counts, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
