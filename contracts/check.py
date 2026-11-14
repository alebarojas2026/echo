"""Check messages against CONTRACTS.md.

    python -m contracts.check session.jsonl            # one message per line
    python -m sim.fake zone_tour --fast | python -m contracts.check -
    python -m contracts.check proof.json               # a .json file is checked as proof.json

Prints file:line and the error for every bad line and exits 1 if any line fails.
A jump in a producer's seq (lost messages) is a warning, not a failure.
"""
import argparse
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

SCHEMAS = Path(__file__).parent / "schemas"
SHOW = 50  # print at most this many failures and warnings per file


def _load():
    schemas = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in SCHEMAS.glob("*.json")}
    registry = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in schemas.values())
    return {name: Draft202012Validator(s, registry=registry) for name, s in schemas.items() if name != "common"}


VALIDATORS = _load()
TYPES = sorted(set(VALIDATORS) - {"proof"})


def errors(msg, schema=None):
    """Contract errors for one parsed message, [] if it is fine. schema defaults to msg["type"]."""
    if schema is None:
        schema = msg.get("type") if isinstance(msg, dict) else None
        if schema not in TYPES:
            return [f"unknown type {schema!r} (expected one of {', '.join(TYPES)})"]
    found = sorted(VALIDATORS[schema].iter_errors(msg), key=lambda e: e.json_path)
    out = [f"{e.json_path}: {e.message[:160]}" for e in found]
    if schema == "state" and not out:
        x = msg["xray"]
        out += [f"$.xray.{k}: has {len(x[k])} cells, w*h is {x['w'] * x['h']}"
                for k in ("moving_db", "static_db") if len(x[k]) != x["w"] * x["h"]]
    return out


def check_lines(lines, schema=None):
    """Check JSON lines. Returns (message count, [(line no, error)], [(line no, warning)]).

    Messages don't name their sender, so a seq that follows any counter of the same src is fine
    (sim uses one counter); else it is compared with the last seq of its type (plus rx and kind for rssi).
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
        failures += [(no, err) for err in errors(msg, schema)]
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


def check_file(path):
    """Check one file ("-" is stdin), print what is wrong and return True if it passes."""
    name = "<stdin>" if path == "-" else path
    with sys.stdin if path == "-" else open(path, encoding="utf-8") as f:
        whole = path.endswith(".json")
        count, failures, warnings = check_lines([f.read()] if whole else f, "proof" if whole else None)
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
    return 0 if all([check_file(f) for f in ap.parse_args(argv).files]) else 1


if __name__ == "__main__":
    sys.exit(main())
