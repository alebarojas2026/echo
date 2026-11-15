"""Check messages against CONTRACTS.md.

    python -m contracts.check session.jsonl            # one message per line
    python -m sim.fake zone_tour --fast | python -m contracts.check -
    python -m contracts.check proof.json               # a .json file is checked as proof.json
    python -m contracts.check --as ask_reply replies.jsonl   # a web server body (ask_question, ask_reply, history, report, layout) or nodes
    python -m contracts.check --layout gate session.jsonl    # against radio/layouts/gate.json, not radio/nodes.json

A state message is checked against a layout: where its nodes stand (near) and how many zones it has (probs).
That layout is radio/nodes.json, unless --layout names another, or
the file sits in a folder named after one of radio/layouts/ (contracts/fixtures/gate/ is checked against
radio/layouts/gate.json whichever layout is in use).

Prints file:line and the error for every bad line and exits 1 if any line fails.
A jump in a producer's seq (lost messages) is a warning, not a failure.
"""
import argparse
import json
import math
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

SCHEMAS = Path(__file__).parent / "schemas"
SHOW = 50  # print at most this many failures and warnings per file
RADIO = Path(__file__).parent.parent / "radio"
LAYOUTS = RADIO / "layouts"   # whole layout files; radio/nodes.json is a copy of one of them (section 3)


def load_layout(name=None) -> dict:
    """A layout file, parsed. name: a file, or the name of one in radio/layouts/ ("gate"). None = the layout
    in use, radio/nodes.json. (Not RADIO_SIGHT_NODES: tests that pin the brain to a layout of their own
    still check what a brain on the repo's layout sends; they name a layout here when they mean another.)"""
    if name is None:
        path = RADIO / "nodes.json"
    else:
        path = Path(name) if Path(name).is_file() else LAYOUTS / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _xy(items) -> dict:
    return {i["id"]: tuple(i["xyz_m"][:2]) for i in items}  # metres


LAYOUT = load_layout()  # section 3
NODES = _xy(LAYOUT["nodes"])
ROUTER_SPOTS = _xy(LAYOUT["router_spots"])
NEAR_M = 0.5


def _load():
    schemas = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in SCHEMAS.glob("*.json")}
    registry = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in schemas.values())
    return {name: Draft202012Validator(s, registry=registry) for name, s in schemas.items() if name != "common"}


VALIDATORS = _load()
# proof.json (section 7), the optional parts of radio/nodes.json (section 3) and the bodies of the board's web
# server: /layout (section 2), POST /ask, GET /history and GET /report (section 10)
NOT_MESSAGES = {"proof", "ask_question", "ask_reply", "history", "report", "layout", "nodes", "privacy", "clock", "clock_set"}
HISTORY_MAX_MS = 30 * 60 * 1000
TYPES = sorted(set(VALIDATORS) - NOT_MESSAGES)


def errors(msg, schema=None, layout=None):
    """Contract errors for one parsed message, [] if it is fine. schema defaults to msg["type"].
    layout: the parsed layout file a state is checked against; None = the layout in use."""
    if schema is None:
        schema = msg.get("type") if isinstance(msg, dict) else None
        if schema not in TYPES:
            return [f"unknown type {schema!r} (expected one of {', '.join(TYPES)})"]
    found = sorted(VALIDATORS[schema].iter_errors(msg), key=lambda e: e.json_path)
    out = [f"{e.json_path}: {e.message[:160]}" for e in found]
    if schema == "state" and not out:
        x = msg["xray"] or {"w": 0, "h": 0, "moving_db": [], "static_db": []}
        out += [f"$.xray.{k}: has {len(x[k])} cells, w*h is {x['w'] * x['h']}"
                for k in ("moving_db", "static_db") if len(x[k]) != x["w"] * x["h"]]
        lesson = (msg["model"]["training"] or {}).get("lesson")
        if lesson and lesson["agree"] > lesson["of"]:
            out.append(f"$.model.training.lesson.agree: {lesson['agree']} of {lesson['of']}")
        things = [(f"$.objects[{i}]", o) for i, o in enumerate(msg["objects"])] + [("$.advice", msg["advice"])]
        nodes, spots = (NODES, ROUTER_SPOTS) if layout is None else (_xy(layout["nodes"]), _xy(layout["router_spots"]))
        zones = len((layout or LAYOUT)["zones"])
        if msg["router"] in spots:
            nodes = {**nodes, "pi5": spots[msg["router"]]}  # the router sits at its current spot
        else:
            out.append(f"$.router: {msg['router']!r} is not a router spot of this layout")
        out += [err for where, thing in things if thing for err in _near(where, thing, nodes)]
        if msg["pred"] and len(msg["pred"]["probs"]) != 1 + zones:
            out.append(f"$.pred.probs: has {len(msg['pred']['probs'])} entries, but this layout has {zones} "
                       f"zone{'s' if zones != 1 else ''}: one entry for empty, then one per zone")
        advice = msg["advice"]
        if advice and advice["to_spot"] is None and (any(advice["move_m"]) or advice["dist_change_m"]):
            out.append("$.advice.move_m: advice with no spot to move to (to_spot null) moves nothing: "
                       "move_m is [0, 0] and dist_change_m is 0")
    if schema in ("ask_reply", "history", "report") and not out:
        out += _stretch(msg, schema)
    return out


def _stretch(msg, schema):
    """Section 10: a stretch of time runs forwards; a history is at most 30 minutes, oldest row first."""
    if schema == "report":
        end = msg["armed_to_t"]
        return [] if end is None or msg["armed_from_t"] <= end else [f"$.armed_to_t: {end} is before armed_from_t"]
    span, where = (msg, "$") if schema == "history" else (msg.get("span"), "$.span")
    if not span:
        return []
    if span["from_t"] > span["to_t"]:
        return [f"{where}.to_t: {span['to_t']} is before from_t"]
    if schema != "history":
        return []
    out = [f"$.to_t: more than 30 minutes after from_t"] if span["to_t"] - span["from_t"] > HISTORY_MAX_MS else []
    times = [row["t"] for row in msg["rows"]]
    if times != sorted(set(times)):
        out.append("$.rows: not oldest first, or one second twice")
    if times and not (span["from_t"] <= times[0] and times[-1] <= span["to_t"]):
        out.append("$.rows: a row outside from_t..to_t")
    return out


def _near(where, thing, nodes=NODES):
    """near names the closest node within 0.5 m of xy_m, or null if none is that close (1 cm slack for rounding)."""
    dist = {n: math.dist(xy, thing["xy_m"]) for n, xy in nodes.items()}
    best = min(dist, key=dist.get)
    want = best if dist[best] <= NEAR_M else None
    if thing["near"] == want or (abs(dist[best] - NEAR_M) <= 0.01 and thing["near"] in (best, None)):
        return []
    return [f"{where}.near: {thing['near']!r}, but the closest node within {NEAR_M} m of {thing['xy_m']} is {want!r}"]


def check_lines(lines, schema=None, layout=None):
    """Check JSON lines. Returns (message count, [(line no, error)], [(line no, warning)]).
    layout: as for errors().

    A producer (one sending socket) keeps one seq counter across all its types, but lines don't name
    the socket. So a seq that follows any counter of the same src is fine; otherwise it is compared
    with the last seq of its type (plus rx and kind for rssi), which always comes from one producer.
    """
    count, failures, warnings, last = 0, [], [], {}
    for no, line in enumerate(lines, 1):
        if not line.strip():
            continue
        count += 1
        try:
            msg = json.loads(line.strip())
        except ValueError as e:
            failures.append((no, f"bad JSON: {e}"))
            continue
        failures += [(no, err) for err in errors(msg, schema, layout)]
        seq = msg.get("seq") if isinstance(msg, dict) else None
        if type(seq) is not int:
            continue
        streams = last.setdefault(msg.get("src"), {})
        key = [msg.get("src"), msg.get("type")] + ([msg.get("rx"), msg.get("kind")] if msg.get("type") == "rssi" else [])
        key = "/".join(map(str, key))
        if seq - 1 not in streams.values() and key in streams:
            warnings.append((no, f"{key}: seq {streams[key]} -> {seq}"))
        streams[key] = seq
    if count == 0:
        failures.append((0, "no messages"))
    return count, failures, warnings


def layout_of(path):
    """The layout a file's states are checked against when nobody says: a file in a folder named after one
    of radio/layouts/ belongs to that layout (contracts/fixtures/gate/). None = the layout in use."""
    for part in reversed(Path(path).parts[:-1]):
        if (LAYOUTS / f"{part}.json").is_file():
            return load_layout(part)
    return None


def check_file(path, schema=None, layout=None):
    """Check one file ("-" is stdin), print what is wrong and return True if it passes.

    schema None = each line by its type; a .json file is always one proof.json.
    layout None = the one the file's folder names (layout_of), else the layout in use."""
    name = "<stdin>" if path == "-" else path
    if layout is None and path != "-":
        layout = layout_of(path)
    with sys.stdin if path == "-" else open(path, encoding="utf-8") as f:
        whole = path.endswith(".json")
        count, failures, warnings = check_lines([f.read()] if whole else f, "proof" if whole else schema, layout)
    for no, text in failures[:SHOW] + [(no, "warning: " + w) for no, w in warnings[:SHOW]]:
        print(f"{name}:{no}: {text}")
    hidden = max(0, len(failures) - SHOW) + max(0, len(warnings) - SHOW)
    if hidden:
        print(f"{name}: ... and {hidden} more")
    print(f"{name}: {count} messages, {len({no for no, _ in failures})} failed, {len(warnings)} seq warnings")
    return not failures


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m contracts.check", description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="+", help="JSON-lines files, - for stdin; a .json file is checked as proof.json")
    ap.add_argument("--as", dest="schema", choices=sorted(NOT_MESSAGES - {"proof"}), default=None,
                    help="check every line as this shape instead of by its type")
    ap.add_argument("--layout", default=None, metavar="NAME|FILE",
                    help="check states against this layout (a name in radio/layouts/, or a file) instead of radio/nodes.json")
    args = ap.parse_args(argv)
    layout = load_layout(args.layout) if args.layout else None
    return 0 if all([check_file(f, args.schema, layout) for f in args.files]) else 1


if __name__ == "__main__":
    sys.exit(main())
