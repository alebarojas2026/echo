"""Replay held-out bus sessions through the brain; write v2 proof numbers."""

import argparse
from bisect import bisect_left
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import platform
import random
from statistics import mean, pstdev
import subprocess


def load_session(path):
    messages = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    metas = [m for m in messages if m.get("type") == "meta"]
    if len(metas) != 1:
        raise ValueError("each file must contain exactly one session meta message")
    if any(m.get("v") != 2 or not isinstance(m.get("recv_t"), (int, float))
           or not math.isfinite(m["recv_t"]) for m in messages):
        raise ValueError("every recorded message needs v2 and finite recv_t")
    if not metas[0].get("session"):
        raise ValueError("session id is required")
    return {"meta": metas[0], "messages": sorted(messages, key=lambda m: m["recv_t"])}


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * fraction
    low = int(index)
    return values[low] + (values[min(low + 1, len(values) - 1)] - values[low]) * (index - low)


def cluster_interval(counts):
    """95% percentile bootstrap by session, preserving overlapping windows."""
    if len(counts) < 2:
        return None
    rng = random.Random(0)
    ratios = []
    for _ in range(2000):
        sample = [rng.choice(counts) for _ in counts]
        total = sum(n for _, n in sample)
        if total:
            ratios.append(sum(c for c, _ in sample) / total)
    return [percentile(ratios, 0.025), percentile(ratios, 0.975)] if ratios else None


def truth(messages, end):
    labels = [m for m in messages if m.get("type") == "label" and end - 1000 <= m["recv_t"] < end]
    if not labels or any(m.get("clipped") for m in labels):
        return None
    if any(m.get("zone") not in range(5) or m.get("persons_in_frame", 0) > 1 for m in labels):
        return None
    zones = Counter(m["zone"] if m.get("present") else 0 for m in labels)
    zone = zones.most_common(1)[0][0]
    mode = Counter(m.get("mode") for m in labels).most_common(1)[0][0]
    kind = "person" if zone else "none"
    if mode == "object":
        recent = [m for m in messages if end - 3000 <= m["recv_t"] < end]
        cameras = [m for m in recent if m.get("type") == "label"]
        if not cameras or any(m.get("persons_in_frame") != 0 or m.get("clipped") for m in cameras):
            return None
        # Object placement must have a confirmed no-person, object-mode history.
        if end - min(m["recv_t"] for m in cameras) < 2000 or any(m.get("mode") != "object" for m in cameras):
            return None
        kind = "object"
    return {"zone": zone, "kind": kind, "labels": len(labels)}


def threshold_zone(links, threshold=3.0):
    """Fixed 3 dB strongest-link baseline; map the link midpoint to a zone."""
    zones = {"pi5>unoq:wifi": 2, "pi5>unoq:ble": 2, "east>unoq:ble": 2,
             "west>unoq:ble": 1, "east>pi5:ble": 4, "west>pi5:ble": 3}
    drops = [(v.get("drop_db"), link) for link, v in links.items()
             if link in zones and v.get("drop_db") is not None]
    if not drops:
        return None
    drop, link = max(drops)
    return zones[link] if drop >= threshold else 0


def object_evidence(messages, end, base):
    for link, baseline in base.items():
        points = [(m["recv_t"], m["dbm"]) for m in messages
                  if m.get("type") == "rssi" and m.get("link") == link
                  and end - 3000 <= m["recv_t"] < end]
        if len(points) >= 2 and points[-1][0] - points[0][0] >= 2000:
            buckets = {}
            for t, value in points:
                buckets.setdefault(int(t // 500), []).append(value)
            values = [mean(v) for _, v in sorted(buckets.items())]
            if all(baseline - v >= 3 for v in values) and pstdev(values) < 0.8:
                return True
    return False


class BrainReplay:
    """Use the real brain state machine, with camera truth kept outside inference."""
    def __init__(self, model, base, expected_hz):
        self.model, self.base, self.expected_hz = model, base, expected_hz
        self.train_sessions = set(model.train_sessions)
        self.train_s = model.train_s

    def replay(self, session):
        from brain.core import Brain
        from brain.features import Windower

        brain = Brain()
        brain.base = dict(self.base)
        brain.expected_hz = dict(self.expected_hz)
        brain.model = self.model
        brain.windower = Windower(self.base)
        last_end = None
        for message in session["messages"]:
            if message.get("type") == "cmd":
                if message.get("cmd") in {"router_moved", "router_home", "reset_alert"}:
                    brain.on_cmd(message)
                continue
            if message.get("type") not in {"rssi", "cam"}:
                continue
            brain.on_message(message)
            window = brain.window
            if window is not None and window["end"] != last_end:
                last_end = window["end"]
                yield {"end": last_end, "pred": brain.pred, "links": window["links"],
                       "ms": brain.decision_ms[-1] if brain.pred is not None and brain.decision_ms else None}


def score(sessions, replay, on_board=False, allow_sim=False, commit=None):
    ids = [s["meta"]["session"] for s in sessions]
    if len(set(ids)) != len(ids) or set(ids) & set(replay.train_sessions):
        raise ValueError("duplicate sessions or training/held-out leakage")
    for session in sessions:
        if session["meta"].get("purpose") != "heldout":
            raise ValueError("only predeclared heldout sessions may be scored")
        if not allow_sim and any(m.get("src") != "live" for m in session["messages"]):
            raise ValueError("sim/replay data is for self-tests, not measured proof")
    correct = total = baseline_correct = baseline_total = po_correct = po_total = 0
    false_alarms = empty_ms = 0
    durations, clusters, used, walkers = [], [], [], set()
    missing_walker = False
    for session in sessions:
        ordered = sorted(session["messages"], key=lambda m: m["recv_t"])
        times = [m["recv_t"] for m in ordered]
        sc = sn = 0
        previous_end, active_false = None, False
        for row in replay.replay(dict(session, messages=ordered)):
            end, prediction = row["end"], row["pred"]
            recent = ordered[bisect_left(times, end - 3000):bisect_left(times, end)]
            actual = truth(recent, end)
            step = min(100, end - previous_end) if previous_end is not None else 0
            previous_end = end
            if actual and actual["kind"] == "object" and not object_evidence(recent, end, replay.base):
                actual = None
            if actual is None or prediction is None:
                active_false = False
                continue
            zone = prediction.get("zone") if prediction.get("present") else 0
            sc += int(zone == actual["zone"])
            sn += 1
            baseline = threshold_zone(row["links"])
            if baseline is not None:
                baseline_correct += int(baseline == actual["zone"])
                baseline_total += 1
            if actual["kind"] in {"person", "object"}:
                po_correct += int(prediction.get("kind") == actual["kind"])
                po_total += 1
            false = actual["kind"] == "none" and prediction.get("kind") == "person"
            if actual["kind"] == "none":
                empty_ms += max(0, step)
                false_alarms += int(false and not active_false)
            active_false = false
            if on_board and row.get("ms") is not None:
                durations.append(row["ms"])
        if sn:
            clusters.append((sc, sn))
            used.append(session["meta"]["session"])
            if session["meta"].get("walker"):
                walkers.add(session["meta"]["walker"])
            else:
                missing_walker = True
        correct += sc
        total += sn
    return {"zone": {"correct": correct if total else None, "total": total or None,
                     "ci95": cluster_interval(clusters), "sessions": used, "walkers": len(walkers) if used and not missing_walker else None,
                     "method": ("SYNTHETIC SELF-TEST; " if allow_sim else "") + "held-out recv_t windows; 95% session bootstrap, 2000 draws; see proof/README.md"},
            "threshold_zone": {"correct": baseline_correct if baseline_total else None, "total": baseline_total or None},
            "person_vs_object": {"correct": po_correct if po_total else None, "total": po_total or None,
                                 "tray_placements": None},
            "false_alarms_per_min": None,
            "train_s": replay.train_s if on_board else None,
            "ms_per_decision": {"p50": percentile(durations, 0.5), "p95": percentile(durations, 0.95)},
            "watts": {"idle": None, "teaching": None, "radio_only": None, "source": None},
            "bytes_out": None, "images_stored": None, "models_on_board": None,
            "measured_at": datetime.now(timezone.utc).isoformat(), "commit": commit}


def read_baseline(path):
    """Read the section 6 baseline artifact, retaining the earlier summary adapter."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "links" in data:
        return ({k: v["base_dbm"] for k, v in data["links"].items()},
                {k: v["expected_hz"] for k, v in data["links"].items()})
    return data["base_dbm"], data["expected_hz"]


def place_start(baseline_path):
    """(epoch ms when the current place began, the session open during its baseline), or (None, None).

    The brain writes place.json next to baseline.json when a baseline asked for by hand finishes.
    Recordings from before it belong to another room or layout and are never scored.
    Without place.json the baseline's own t is the cut-off.
    """
    baseline_path = Path(baseline_path)
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    if not isinstance(baseline, dict):
        return None, None
    try:
        t = json.loads(baseline_path.with_name("place.json").read_text(encoding="utf-8"))["t"]
    except (OSError, ValueError, KeyError, TypeError):
        t = baseline.get("t")
    if isinstance(t, bool) or not isinstance(t, (int, float)):
        return None, None
    return t, baseline.get("session")


def from_this_place(session, start, open_session=None):
    """True when a loaded session was recorded in the current place."""
    meta = session["meta"]
    return start is None or meta["recv_t"] >= start or (open_session and meta.get("session") == open_session)


def merge_scored(proof, report):
    from proof.provenance import prepare_update
    out = prepare_update(proof, report["commit"], report["measured_at"])
    for key in ("zone", "threshold_zone", "person_vs_object"):
        out[key] = report[key]
    if report["train_s"] is not None:
        out["train_s"] = report["train_s"]
    if report["ms_per_decision"]["p50"] is not None:
        out["ms_per_decision"] = report["ms_per_decision"]
    for key, value in report.items():
        out.setdefault(key, value)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", nargs="+", required=True, type=Path)
    parser.add_argument("--heldout", nargs="+", required=True, type=Path)
    parser.add_argument("--baseline", type=Path, default=Path(__file__).resolve().parents[1] / "data/sessions/baseline.json")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().with_name("proof.json"))
    parser.add_argument("--on-board", action="store_true", help="record timing only on the UNO Q")
    parser.add_argument("--allow-sim", action="store_true", help="self-tests only; output cannot be named proof.json")
    args = parser.parse_args()
    if args.allow_sim and args.output.name == "proof.json":
        parser.error("synthetic checks need a separately named output")
    board_model = Path("/proc/device-tree/model")
    board_name = board_model.read_text().lower() if board_model.exists() else ""
    if args.on_board and (platform.system() != "Linux" or not any(n in board_name for n in ("uno q", "qrb2210"))):
        parser.error("board timing requires the UNO Q device-tree identity")
    training, heldout = [load_session(p) for p in args.train], [load_session(p) for p in args.heldout]
    if any(s["meta"].get("purpose") not in {"train", "object"} for s in training):
        parser.error("training inputs must have train or object purpose")
    if {s["meta"]["session"] for s in training} & {s["meta"]["session"] for s in heldout}:
        parser.error("training and heldout sessions overlap")
    start, open_session = place_start(args.baseline)
    old = [s["meta"]["session"] for s in training + heldout if not from_this_place(s, start, open_session)]
    if old:
        parser.error("recorded before the current baseline (another place): " + ", ".join(sorted(old)))
    if not args.allow_sim and any(m.get("src") != "live" for s in training for m in s["messages"]):
        parser.error("synthetic training cannot produce measured proof")
    from brain.train import Model

    base, rates = read_baseline(args.baseline)
    model = Model(base).fit(training)
    adapter = BrainReplay(model, base, rates)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    report = score(heldout, adapter, args.on_board, args.allow_sim, commit)
    if args.output.exists():
        report = merge_scored(json.loads(args.output.read_text()), report)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
