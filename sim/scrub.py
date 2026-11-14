"""Remove MAC addresses, BSSIDs and device names from a session file before it is committed.

    python -m sim.scrub data/sessions/s12.jsonl data/sessions/keep/s12.jsonl
    python -m sim.scrub --check data/sessions/keep/s12.jsonl     # exit 1 if anything is left

What it does to every JSON line:
  - deletes any field whose name says it holds an identifier (mac, bssid, ssid, name, ...);
  - blanks anything that looks like a MAC address inside any other text.
Contract fields (CONTRACTS.md v2) are never touched, so a scrubbed file still replays.
"""
import argparse
import json
import re
import sys

# Field names that hold a device identifier, wherever they appear in a message.
ID_KEYS = {"mac", "bssid", "ssid", "essid", "addr", "address", "bdaddr", "peer", "name",
           "device", "device_name", "local_name", "complete_local_name", "hostname", "host"}
# aa:bb:cc:dd:ee:ff, AA-BB-CC-DD-EE-FF and aabb.ccdd.eeff
MAC = re.compile(r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{2}([:-]))(?:[0-9A-Fa-f]{2}\1){4}[0-9A-Fa-f]{2}(?![0-9A-Fa-f])"
                 r"|(?<![0-9A-Fa-f])[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}(?![0-9A-Fa-f])")
BLANK = "[removed]"


def _clean(value, found: list):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k.lower() in ID_KEYS:
                found.append(k)
            else:
                out[_clean(k, found)] = _clean(v, found)
        return out
    if isinstance(value, list):
        return [_clean(v, found) for v in value]
    if isinstance(value, str):
        found.extend("mac" for _ in MAC.finditer(value))
        return MAC.sub(BLANK, value)
    return value


def scrub_line(line: str):
    """Return (clean line, list of what was removed). Lines that are not JSON are scrubbed as text."""
    found: list = []
    try:
        msg = json.loads(line)
    except ValueError:
        return _clean(line, found), found
    return json.dumps(_clean(msg, found), separators=(",", ":")), found


def scrub(lines):
    """Yield (clean line, what was removed) for every non-blank line."""
    for line in lines:
        if line.strip():
            yield scrub_line(line.strip())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("src", help="session .jsonl file")
    ap.add_argument("dst", nargs="?", help="where to write the clean copy (default: stdout)")
    ap.add_argument("--check", action="store_true", help="write nothing; exit 1 if the file has identifiers")
    args = ap.parse_args(argv)
    with open(args.src) as f:
        results = list(scrub(f))
    removed = sum(len(found) for _, found in results)
    dirty = sum(1 for _, found in results if found)
    print(f"{args.src}: {removed} identifiers in {dirty} of {len(results)} lines", file=sys.stderr)
    if args.check:
        return 1 if removed else 0
    text = "".join(line + "\n" for line, _ in results)
    if args.dst:
        with open(args.dst, "w") as f:
            f.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
