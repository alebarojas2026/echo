"""Check messages against CONTRACTS.md.

    python -m contracts.check session.jsonl            # one message per line
    python -m sim.fake zone_tour --fast | python -m contracts.check -
    python -m contracts.check proof.json               # a .json file is checked as proof.json

Prints file:line and the error for every bad line and exits 1 if any line fails.
A jump in seq from one producer is printed as a warning (lost messages), not a failure.
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


def _short(text, n=160):
    return text if len(text) <= n else text[:n] + "..."


def errors(msg, schema=None):
    """Contract errors for one parsed message, [] if it is fine. schema defaults to msg["type"]."""
    if schema is None:
        if not isinstance(msg, dict):
            return ["not a JSON object"]
        schema = msg.get("type")
        if schema not in TYPES:
            return [f"unknown type {schema!r} (expected one of {', '.join(TYPES)})"]
    found = sorted(VALIDATORS[schema].iter_errors(msg), key=lambda e: e.json_path)
    out = [f"{e.json_path}: {_short(e.message)}" for e in found]
    if schema == "state" and not out:
        xray = msg["xray"]
        cells = xray["w"] * xray["h"]
        out += [f"$.xray.{k}: has {len(xray[k])} cells, w*h is {cells}"
                for k in ("moving_db", "static_db") if len(xray[k]) != cells]
    return out


def producer(msg):
    """Who sent a message. Each producer keeps its own seq counter."""
    key = [msg.get("src"), msg.get("type")]
    if msg.get("type") == "rssi":  # three readers: wifi on unoq, ble on unoq, ble on pi5
        key += [msg.get("rx"), msg.get("kind")]
    return "/".join(str(k) for k in key)


def check_lines(lines):
    """Check JSON lines. Returns (message count, [(line no, error)], [(line no, warning)])."""
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
        failures += [(no, err) for err in errors(msg)]
        seq = msg.get("seq") if isinstance(msg, dict) else None
        if type(seq) is not int:
            continue
        who = producer(msg)
        prev = last.get(who)
        if prev is not None and seq != prev + 1:
            gap = f"{seq - prev - 1} lost" if seq > prev else "repeated" if seq == prev else "went back"
            warnings.append((no, f"{who}: seq {prev} -> {seq} ({gap})"))
        last[who] = seq
    if count == 0:
        failures.append((0, "no messages"))
    return count, failures, warnings


def check_proof(text):
    """Check a whole proof.json document. Returns a list of errors."""
    try:
        doc = json.loads(text)
    except ValueError as e:
        return [f"bad JSON: {e}"]
    return errors(doc, "proof")


def check_file(path):
    """Check one file ("-" is stdin), print what is wrong and return True if it passes."""
    name = "<stdin>" if path == "-" else path
    if path == "-":
        stream = sys.stdin
    else:
        stream = open(path, encoding="utf-8")
    with stream:
        if path.endswith(".json"):
            failures = [(1, e) for e in check_proof(stream.read())]
            count, warnings = 1, []
        else:
            count, failures, warnings = check_lines(stream)
    for no, err in failures[:SHOW]:
        print(f"{name}:{no}: {err}")
    for no, warn in warnings[:SHOW]:
        print(f"{name}:{no}: warning: {warn}")
    hidden = max(0, len(failures) - SHOW) + max(0, len(warnings) - SHOW)
    if hidden:
        print(f"{name}: ... and {hidden} more")
    bad_lines = len({no for no, _ in failures})
    print(f"{name}: {count} messages, {bad_lines} failed, {len(warnings)} seq warnings")
    return not failures


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m contracts.check", description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="+", help="JSON-lines files, - for stdin; a .json file is checked as proof.json")
    args = ap.parse_args(argv)
    results = [check_file(f) for f in args.files]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
