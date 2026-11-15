"""A live run on the kit, counted from what the board itself said at the time. Nothing is replayed.

    python -m proof.said_live <session.jsonl> --stands 10 --empty-tail-s 120 --commit <board commit> --output proof/proof.live.json
    python -m proof.render_table --live proof/proof.live.json --output PROOF.md

For a run recorded by the bus with no capture of the brain's states. The bus file still holds the
narrator's sentences, and each one names the board's own event it was said for (`event_kind`,
`event_id`). So the arrivals and leavings the board said, live, can be counted from the file.

The truth is the operator's written count: how many stands, and how long the spot was left empty
at the end. There is no timed log, so this gives a count and nothing finer:
- found = the stands for which the board said an arrival, each followed by its leaving;
- an arrival said beyond the number of stands, or inside the empty tail, is a false one.

What it cannot show: the board's ten-times-a-second decisions were not recorded. A "somebody" too
short to be said as an arrival would not be in the file, so the empty tail is "no arrival said",
not "no false presence". The narrator says at most one sentence every 8 s; arrivals closer than
that could be missed, which only makes the count lower.
"""
import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from proof.shuffled import plain_range

METHOD = "the board's own arrivals and leavings as its narrator recorded them live; operator count as truth; nothing replayed"
WORDS = "one person, one run, live on the kit: decisions made by the board at the time, not replayed"


def count(path, stands, empty_tail_s, commit):
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    metas = [r for r in rows if r.get("type") == "meta"]
    if len(metas) != 1 or not metas[0].get("session"):
        raise ValueError("exactly one named session meta is required")
    if any(r.get("src") != "live" or not isinstance(r.get("recv_t"), (int, float)) or not math.isfinite(r["recv_t"]) for r in rows):
        raise ValueError("only live recordings with receive times are measured input")
    if not isinstance(commit, str) or len(commit) != 40:
        raise ValueError("the full commit the board ran is required")
    if not isinstance(stands, int) or stands < 1 or not empty_tail_s > 0:
        raise ValueError("the operator's count of stands and the length of the empty tail are required")
    start, end = metas[0]["recv_t"], max(r["recv_t"] for r in rows)
    tail = end - empty_tail_s * 1000
    if tail <= start or not any(r.get("type") == "rssi" and r["recv_t"] >= end - 1000 for r in rows):
        raise ValueError("the recording is shorter than its empty tail, or its readings stop early")
    said, seen = [], set()
    for r in rows:
        if r.get("type") != "narration" or r.get("event_id") in seen:
            continue                     # a second sentence for the same event replaces the first: one event
        seen.add(r.get("event_id"))
        # the event is older than its sentence by the time the sentence took to make
        said.append({"t": r["recv_t"] - (r.get("gen_ms") or 0), "kind": r.get("event_kind"), "id": r.get("event_id")})
    said.sort(key=lambda e: e["t"])
    before = [e for e in said if e["t"] < tail]
    arrivals = [i for i, e in enumerate(before) if e["kind"] == "enter"]
    complete = sum(i + 1 < len(before) and before[i + 1]["kind"] == "exit" for i in arrivals)
    held = [round((before[i + 1]["t"] - before[i]["t"]) / 1000, 1) for i in arrivals
            if i + 1 < len(before) and before[i + 1]["kind"] == "exit"]
    other = sorted({e["kind"] for e in said if e["kind"] not in ("enter", "exit")})
    return {"source": "live", "method": METHOD, "words": WORDS, "session": metas[0]["session"],
            "recording_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(), "commit": commit,
            "measured_at": datetime.fromtimestamp(end / 1000, timezone.utc).isoformat(),
            "stands": stands, "found": min(stands, complete), "arrivals_said": len(arrivals),
            "extra_arrivals": max(0, len(arrivals) - stands), "held_s": held, "other_events_said": other,
            "empty_tail_s": round((end - tail) / 1000, 1),
            "tail_arrivals": sum(e["kind"] == "enter" for e in said if e["t"] >= tail),
            "tail_events": sum(1 for e in said if e["t"] >= tail)}


def table(result):
    """The live rows for PROOF.md's generated block."""
    from proof.render_table import cell
    if result.get("method") != METHOD or result.get("source") != "live" or len(result.get("commit") or "") != 40:
        raise ValueError("only a live run with its board commit is publishable")
    date = datetime.fromisoformat(result["measured_at"]).date().isoformat() + " UTC"
    held = f" The board held each for {min(result['held_s'])} to {max(result['held_s'])} s." if result["held_s"] else ""
    rows = [("Live: stands for which the board said an arrival", plain_range(result["found"], result["stands"], "stands found"),
             f"{result['words']}. Counted from the arrivals and leavings the board said, as its narrator recorded them; "
             f"{result['arrivals_said']} arrivals said for {result['stands']} stands, {result['extra_arrivals']} too many.{held}",
             f"{result['stands']} stands of about 10 s"),
            ("Live: arrivals said on the empty spot afterwards",
             f"{result['tail_arrivals']} in {result['empty_tail_s'] / 60:.1f} empty minutes",
             f"{result['words']}. The last {result['empty_tail_s']:.0f} s of the same recording, with the spot left empty: "
             f"{result['tail_events']} events of any kind said. The board's ten-times-a-second decisions were not recorded, so this is "
             "\"no arrival said\", not \"no false presence\".",
             f"{result['empty_tail_s'] / 60:.1f} minutes")]
    out = ["", "## Live on the kit (the board's own decisions, not replayed)", "",
           "| Number | Value | Method | N | Recorded | Board build |", "|---|---|---|---|---|---|"]
    out += ["| " + " | ".join(cell(c) for c in (*row, date, result["commit"][:7])) + " |" for row in rows]
    out += ["", f"{cell(result['session'])}: recording SHA256 `{result['recording_sha256']}`. The truth is the operator's count "
            "(how many stands, how long empty); there is no timed log, so no delay and no per-second number comes from this run. "
            "See proof/said_live.py."]
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("recording", type=Path)
    parser.add_argument("--stands", type=int, required=True, help="the operator's count of stands")
    parser.add_argument("--empty-tail-s", type=float, required=True, help="how long the spot was left empty at the end")
    parser.add_argument("--commit", required=True, help="the full commit the board ran")
    parser.add_argument("--output", type=Path, help="write the companion report here; omit to preview")
    args = parser.parse_args(argv)
    result = count(args.recording, args.stands, args.empty_tail_s, args.commit)
    text = "\n".join(table(result))
    if args.output:
        args.output.write_text(json.dumps(result, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
