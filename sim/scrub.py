"""Remove MAC addresses, BSSIDs and device names from a session file before it is committed.

    python -m sim.scrub data/sessions/s12.jsonl data/sessions/keep/s12.jsonl
    python -m sim.scrub --check data/sessions/keep/s12.jsonl     # exit 1 if anything is left

What it does to every JSON line:
  - deletes any field whose name says it holds an identifier (mac, bssid, ssid, name, ...);
  - blanks anything shaped like a MAC address inside any other text (with :, -, _ or . between
    the bytes); 12 hex digits in a row are blanked only under a field named like an address
    (its name contains mac, addr or bssid).
Contract fields (CONTRACTS.md v2) are never touched, so a scrubbed file still replays.
"""
import argparse
import json
import re
import sys

# Field names that hold a device identifier, wherever they appear in a message.
ID_KEYS = {"mac", "bssid", "ssid", "essid", "addr", "address", "bdaddr", "peer", "name",
           "device", "device_name", "local_name", "complete_local_name", "hostname", "host"}
# Address shapes, none of them inside a longer run of hex digits:
#   aa:bb:cc:dd:ee:ff   AA-BB-CC-DD-EE-FF   AA_BB_CC_DD_EE_FF (BlueZ paths, dev_AA_BB_...)   aabb.ccdd.eeff
_H = "[0-9A-Fa-f]"
MAC = re.compile(rf"(?<!{_H})(?:{_H}{{2}}([:_-])(?:{_H}{{2}}\1){{4}}{_H}{{2}}"
                 rf"|{_H}{{4}}\.{_H}{{4}}\.{_H}{{4}})(?!{_H})")
# 12 hex digits with no separators look like any other hex (a short commit hash, the end of a
# UUID), so they are only blanked under a field whose name says it holds an address.
BARE = re.compile(rf"(?<!{_H}){_H}{{12}}(?!{_H})")
ADDRESS_KEY = re.compile(r"mac|addr|bssid", re.IGNORECASE)
BLANK = "[removed]"


def _clean(value, found: list, address: bool = False):
    """`address` is true for values under a field named like an address (src_mac, peer_addr, ...)."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k.lower() in ID_KEYS:
                found.append(k)
            else:
                out[_clean(k, found)] = _clean(v, found, bool(ADDRESS_KEY.search(k)))
        return out
    if isinstance(value, list):
        return [_clean(v, found, address) for v in value]
    if isinstance(value, str):
        for pattern in (MAC, BARE) if address else (MAC,):
            found.extend("mac" for _ in pattern.finditer(value))
            value = pattern.sub(BLANK, value)
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
