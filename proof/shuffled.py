"""Shuffled trials and an empty hour: presence numbers we can defend (one spot, one zone).

    OPERATOR_KEY=... python -m proof.shuffled trials <session> <walker> --tuning   # choose settings on this one
    OPERATOR_KEY=... python -m proof.shuffled trials <session> <walker>            # report from this one
    OPERATOR_KEY=... python -m proof.shuffled empty <session> --minutes 60
    python -m proof.shuffled tune   data/sessions/<session>.shuffled.jsonl         # tuning recordings only
    python -m proof.shuffled report data/sessions/<session>.shuffled.jsonl         # never a tuning recording

A trial run is 40 trials of 20 s in an order the person can't predict: 16 stand on the spot,
12 empty, 12 walk through without stopping. Each is followed by 5 s to step away, not scored.
The space is armed throughout, so a walk-through comes out as passed-by, intrusion or nothing.

Everything is scored from the brain's own states and events, as this tool heard them on the
WebSocket, on this tool's clock. One file holds it all: a header, the trial marks, the states
(reduced to present / kind) and the events. Nothing is scored from memory or by hand.

Tuned on one recording, reported from another: a recording is made as tuning or as report and
keeps that role for good. `report` refuses a tuning recording; `tune` refuses a report one, so
looking at a report recording while choosing settings isn't something this tool will do.
"""
import argparse
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from statistics import median



def with_key(msg):
    """The cmd with the board's operator key from OPERATOR_KEY (environment only), when one is set."""
    key = os.environ.get("OPERATOR_KEY")
    return dict(msg, key=key) if key else msg

TRIAL_S, REST_S = 20, 5
KINDS = {"stand": 16, "empty": 12, "walk": 12}
PRESENT_MS, MAX_GAP_MS = 300, 500
CUES = {"stand": "Step onto the spot and stand still.",
        "empty": "Stay out. Nobody on the spot.",
        "walk": "Walk through the spot without stopping."}


def plan(seed):
    """The 40 trial kinds in a shuffled order. The seed is kept in the file, never shown first."""
    kinds = [k for k, n in KINDS.items() for _ in range(n)]
    random.Random(seed).shuffle(kinds)
    return kinds


def exact_interval(k, n, level=0.95):
    """The exact (Clopper-Pearson) interval for k of n, by bisection on the binomial tail."""
    if n <= 0:
        return None

    def tail_ge(p, k):   # P(X >= k) for X ~ Binomial(n, p)
        from math import comb
        return sum(comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))

    def solve(f, target):
        lo, hi = 0.0, 1.0
        for _ in range(60):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if f(mid) < target else (lo, mid)
        return (lo + hi) / 2

    alpha = (1 - level) / 2
    low = 0.0 if k == 0 else solve(lambda p: tail_ge(p, k), alpha)
    high = 1.0 if k == n else solve(lambda p: tail_ge(p, k + 1), 1 - alpha)   # P(X <= k) = alpha
    return low, high


def plain_range(k, n, what):
    """"15 of 16 detected; with this few trials the true rate is probably between 70% and 99%"."""
    if not n:
        return f"0 trials {what}: nothing to report"
    low, high = exact_interval(k, n)
    lo, hi = math.floor(low * 100), math.ceil(high * 100)  # outward, never narrow the exact interval
    few = "with this few trials " if n < 100 else ""
    return f"{k} of {n} {what}; {few}the true rate is probably between {lo}% and {hi}%"


def read(path):
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows or rows[0].get("type") != "header" or rows[0].get("role") not in ("tuning", "report"):
        raise ValueError(f"{path}: not a shuffled-trials recording (no header with a role)")
    return rows[0], rows[1:]


def present_runs(states, t0, t1, minimum_ms=PRESENT_MS):
    """Presence starts, without bridging unknown states or gaps; empty tests count every blip."""
    starts, first, previous, confirmed = [], None, None, False
    for s in states:
        if not (t0 <= s["t"] < t1):
            continue
        if previous is None or not 0 < s['t'] - previous <= MAX_GAP_MS:
            first, confirmed = None, False
        previous = s['t']
        if s["present"] and not s.get('hidden'):
            first = s['t'] if first is None else first
            if not confirmed and s['t'] - first >= minimum_ms:
                starts.append(first)
                confirmed = True
        else:
            first, confirmed = None, False
    return starts


def coverage(states, t0, t1):
    """Known adjacent state intervals; a dropped connection is never clean empty exposure."""
    heard = [s for s in states if t0 <= s['t'] < t1]
    return [(a['t'], b['t']) for a,b in zip(heard, heard[1:])
            if not a.get('hidden') and not b.get('hidden') and 0 < b['t']-a['t'] <= MAX_GAP_MS]


def score(header, rows):
    """Counts from one recording. A trial with no state heard during it is left out, and counted as such."""
    states = sorted((r for r in rows if r.get("type") == "state"), key=lambda r: r["t"])
    events = [r for r in rows if r.get("type") == "event"]
    out = {"session": header["session"], "role": header["role"], "mode": header["mode"],
           "src": header.get("src"), "commit": header.get("commit")}
    if header["mode"] == "empty":
        marks = [r for r in rows if r.get("type") == "span"]
        t0, t1 = (marks[0]["t0"], marks[0]["t1"]) if marks else (None, None)
        heard = [s for s in states if t0 is not None and t0 <= s["t"] < t1]
        spans = coverage(heard, t0, t1) if heard else []
        hours = sum(b-a for a,b in spans) / 3_600_000
        presences = len(present_runs(states, t0, t1, minimum_ms=0)) if heard else 0
        intrusions = sum(1 for e in events if e["kind"] == "intrusion" and any(a <= e['t'] < b for a,b in spans))
        out.update(recorded_minutes=round(hours * 60, 1), false_presences=presences, false_intrusions=intrusions,
                   false_presences_per_hour=round(presences / hours, 2) if hours else None,
                   false_intrusions_per_hour=round(intrusions / hours, 2) if hours else None)
        return out
    trials = [r for r in rows if r.get("type") == "trial"]
    stand = {"n": 0, "detected": 0, "seconds": []}
    empty = {"n": 0, "false": 0}
    walk = {"n": 0, "passed_by": 0, "intrusion": 0, "nothing": 0}
    unheard = 0
    for tr in trials:
        t0, t1 = tr["t0"], tr["t1"]
        spans = coverage(states, t0, t1)
        if (not spans or spans[0][0]-t0 > MAX_GAP_MS or t1-spans[-1][1] > MAX_GAP_MS
                or any(a[1] != b[0] for a,b in zip(spans,spans[1:]))):
            unheard += 1
            continue
        runs = present_runs(states, t0, t1, minimum_ms=0 if tr['kind'] == 'empty' else PRESENT_MS)
        if tr["kind"] == "stand":
            stand["n"] += 1
            if runs:
                stand["detected"] += 1
                stand["seconds"].append(round((runs[0] - t0) / 1000, 1))
        elif tr["kind"] == "empty":
            empty["n"] += 1
            empty["false"] += int(bool(runs))
        else:
            walk["n"] += 1
            kinds = {e["kind"] for e in events if t0 <= e["t"] < t1 + REST_S * 1000}
            walk["intrusion" if "intrusion" in kinds else "passed_by" if "passed_by" in kinds else "nothing"] += 1
    secs = sorted(stand["seconds"])
    out.update(trials=len(trials), unheard_trials=unheard, stand=stand, empty=empty, walk=walk,
               median_detect_s=median(secs) if secs else None)
    return out


def lines(result):
    """The result in plain sentences, for the terminal and PROOF.md."""
    if result["mode"] == "empty":
        return [f"Empty for {result['recorded_minutes']} minutes actually recorded: "
                f"{result['false_presences']} false \"someone is here\", {result['false_intrusions']} false intrusions "
                f"({result['false_presences_per_hour']} and {result['false_intrusions_per_hour']} an hour)."]
    s, e, w = result["stand"], result["empty"], result["walk"]
    out = [plain_range(s["detected"], s["n"], "detected") + ".",
           plain_range(e["false"], e["n"], "empty trials showed someone") + "."]
    if result["median_detect_s"] is not None:
        out.append(f"Median time from the cue to \"someone is here\": {result['median_detect_s']} s "
                   "(this includes the person's time to step on).")
    out.append(f"Walk-throughs ({w['n']}): {w['passed_by']} passed by, {w['intrusion']} intrusion, {w['nothing']} nothing.")
    if result["unheard_trials"]:
        out.append(f"{result['unheard_trials']} trials left out: state coverage was incomplete or unknown.")
    return out


def for_report(header, rows=()):
    if header["role"] != "report":
        raise ValueError(f"{header['session']} is a tuning recording: its numbers chose the settings, so they are "
                         "never reported. Record a new one without --tuning.")
    if header.get("src") != "live":
        raise ValueError(f"{header['session']} is not a live recording (src {header.get('src')}): not measured proof")
    if any(r.get('src') != 'live' for r in rows if r.get('type') == 'state'):
        raise ValueError('mixed or non-live states are not measured proof')
    times = [r.get('t') for r in rows if r.get('type') in ('state','event')]
    if any(isinstance(t,bool) or not isinstance(t,(int,float)) or not math.isfinite(t) for t in times) or any(
            a > b for a,b in zip(times,times[1:])):
        raise ValueError('invalid or reversed capture clock; do not report this recording')


def for_tuning(header):
    if header["role"] != "tuning":
        raise ValueError(f"{header['session']} is a report recording: looking at it while choosing settings would "
                         "spoil it. Tune on a recording made with --tuning.")


# ---- recording (needs the brain's WebSocket) ----

def speak(text, say=print):
    say(text)
    if shutil.which("say"):   # a spoken cue where the laptop has one
        subprocess.Popen(["say", text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def guide(kinds, mark, say=print, sleep=time.sleep, clock=time.time):
    """Cue each trial and mark its start and end. The order is said one trial at a time."""
    for i, kind in enumerate(kinds, 1):
        t0 = int(clock() * 1000)
        say(f"Trial {i} of {len(kinds)}. {CUES[kind]}")
        sleep(TRIAL_S)
        mark({"type": "trial", "n": i, "kind": kind, "t0": t0, "t1": int(clock() * 1000)})
        say("Step away from the spot.")
        sleep(REST_S)


def keep(msg, write, clock=time.time):
    """A brain state or event, reduced to what the scores need, stamped on our clock."""
    t = int(clock() * 1000)
    if msg.get("type") == "state":
        pred = msg.get("pred")
        write({"type": "state", "t": t, "present": bool(pred and pred.get("present")),
               "kind": pred.get("kind") if pred else None, "hidden": pred is None, "src": msg.get("src")})
    elif msg.get("type") == "event" and msg.get("kind") in ("intrusion", "passed_by", "enter", "exit"):
        write({"type": "event", "t": t, "kind": msg["kind"]})


def record(args, mode):
    from websockets.sync.client import connect
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", args.session):
        sys.exit("use a new simple session id")
    path = Path(args.sessions) / f"{args.session}.shuffled.jsonl"
    seed = random.SystemRandom().randrange(2 ** 32)
    lock = threading.Lock()
    src = []
    with path.open("x", encoding="utf-8") as f, connect(args.url) as ws:
        def write(row):
            with lock:
                f.write(json.dumps(row) + "\n")
                f.flush()
            if row.get("type") == "state" and row.get("src") and not src:
                src.append(row["src"])

        def send(name, **a):
            ws.send(json.dumps(with_key({"v": 2, "type": "cmd", "cmd": name, "args": a})))

        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip() or None
        first = json.loads(ws.recv())
        header = {"type": "header", "session": args.session, "mode": mode,
                  "role": "tuning" if args.tuning else "report", "walker": getattr(args, "walker", None),
                  "seed": seed, "src": first.get("src"), "commit": commit, "t": int(time.time() * 1000)}
        write(header)
        listener = threading.Thread(target=lambda: [keep(json.loads(raw), write) for raw in ws], daemon=True)
        listener.start()
        send("arm", on=True)
        try:
            if mode == "trials":
                guide(plan(seed), write, say=speak)
            else:
                t0 = int(time.time() * 1000)
                print(f"Keep the spot empty for {args.minutes} minutes. Ctrl-C ends it early; the length recorded is reported.")
                try:
                    time.sleep(args.minutes * 60)
                except KeyboardInterrupt:
                    pass
                write({"type": "span", "t0": t0, "t1": int(time.time() * 1000)})
        finally:
            send("arm", on=False)
    print(f"saved {path}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("trials", "empty"):
        p = sub.add_parser(name)
        p.add_argument("session")
        if name == "trials":
            p.add_argument("walker", help="a pseudonym")
        else:
            p.add_argument("--minutes", type=float, default=60)
        p.add_argument("--tuning", action="store_true", help="this recording is for choosing settings; never reported")
        p.add_argument("--url", default="ws://192.168.77.2:8765/ws")
        p.add_argument("--sessions", default=str(Path(__file__).resolve().parents[1] / "data" / "sessions"))
    for name in ("tune", "report"):
        p = sub.add_parser(name)
        p.add_argument("file")
        p.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd in ("trials", "empty"):
        return record(args, args.cmd)
    header, rows = read(args.file)
    try:
        for_report(header, rows) if args.cmd == "report" else for_tuning(header)
    except ValueError as e:
        sys.exit(str(e))
    result = score(header, rows)
    print(json.dumps(result, indent=1) if args.json else "\n".join(lines(result)))


if __name__ == "__main__":
    main()
