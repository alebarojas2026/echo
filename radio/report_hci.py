"""Gate-2 Bluetooth raw scan report helper.

Reads the Gate 2 table in ``radio/GATE.md`` and prints a pass/fail summary.

Usage (on the board, after a live run):
    python -m radio.report_hci

Pass criteria (the lowest rate written for each link), for every ble link in radio/nodes.json, taken
from what the beacon can give (min_rate):
    a beacon sends one advertising event every interval + 5 ms on average (the controller's random
    0-10 ms advDelay); a continuous scanner hears at most one copy per event, on the one channel it
    is listening to. So an ESP32 at 35 ms gives at most 25 a second, a Pi at 20 ms 40.
    A link passes when its receiver hears 30% of those events (the hall loses the rest), and never
    under 7 a second, the fewest that keep a 1 s window and the 0.5 s means of the brain's rules
    filled. That is 7.5/s for E and W, 12/s for a Pi's beacon (S, B).

The verdict comes from the rates alone. One row per run is fine: the lowest one counts.
The Result column is only cross-checked, so it can stay `__`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from .nodes import DOC, LINKS

GATE_PATH = Path(__file__).resolve().parent / "GATE.md"

# Built from radio/nodes.json, so a new layout (a second Pi, #459) needs no edit here.
_PIS = {n["id"] for n in DOC["nodes"] if "receiver" in n["roles"] and "beacon" in n["roles"]}
_LETTER = {p["node"]: p["id"] for p in DOC["beacons"]["payloads"]}

ADV_DELAY_MS = 5.0    # the controller's random 0-10 ms advDelay on every event, on average (Core Vol 6 Part B 4.4.2.2.1)
ESP32_ADV_MS = 35.0   # beacon/beacon.ino: INTERVAL = 56 x 0.625 ms
PI_ADV_MS = 20.0      # pi/radio_node.py: ADV_INTERVAL_HCI = 32 x 0.625 ms (its log says when the controller refuses it)
HEARD_SHARE = 0.3     # the share of a beacon's events a receiver must hear
BRAIN_MIN_HZ = 7.0    # never pass under this: fewer readings leave the brain's 1 s windows and 0.5 s means thin


def events_hz(tx: str) -> float:
    """At most how many adverts a second a continuous scanner can hear from beacon node `tx`."""
    return 1000.0 / ((PI_ADV_MS if tx in _PIS else ESP32_ADV_MS) + ADV_DELAY_MS)


def min_rate(link_id: str) -> float:
    """Gate 2's pass rate for a Bluetooth link: HEARD_SHARE of what its beacon can give, at least BRAIN_MIN_HZ."""
    return round(max(BRAIN_MIN_HZ, HEARD_SHARE * events_hz(LINKS[link_id]["tx"])), 1)


MIN_RATES: dict[str, float] = {link_id: min_rate(link_id)
                               for link_id, link in LINKS.items() if link["kind"] == "ble"}
BEACON_OF = {link_id: _LETTER[LINKS[link_id]["tx"]] for link_id in MIN_RATES}
UNMEASURED = "__"

_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def gate2_section(text: str) -> str:
    """The text under the '## Gate 2' heading, up to the next '## ' heading (all of it if there's none)."""
    m = re.search(r"^##\s*Gate 2\b.*?$(?P<body>.*?)(?=^##\s|\Z)", text, re.MULTILINE | re.DOTALL)
    return m.group("body") if m else text


def parse_gate2_md(text: str) -> dict[str, list[dict]]:
    """Every Gate 2 table row, by link id: [{beacon, rate, rate_text, result}, ...].

    rate is a float, or None when the cell is `__` or can't be read (rate_text keeps what was written).
    """
    rows: dict[str, list[dict]] = {}
    for line in gate2_section(text).splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        link = cells[0].strip("`").lower()
        if link not in MIN_RATES or len(cells) < 3:
            continue
        rate_text = cells[2]
        rate = float(rate_text) if _NUMBER.fullmatch(rate_text) else None
        rows.setdefault(link, []).append({
            "beacon": cells[1].upper(),
            "rate": rate,
            "rate_text": rate_text,
            "result": cells[3].upper() if len(cells) > 3 else UNMEASURED,
        })
    return rows


def lowest(entries: list[dict]) -> float | None:
    rates = [e["rate"] for e in entries if e["rate"] is not None]
    return min(rates) if rates else None


def check(rows: dict[str, list[dict]]) -> list[str]:
    """Return a list of failure reasons, empty means PASS."""
    failures: list[str] = []
    for link, min_rate in MIN_RATES.items():
        entries = rows.get(link)
        if not entries:
            failures.append(f"{link} not found in the Gate 2 table")
            continue
        for e in entries:
            if e["beacon"] != BEACON_OF[link]:
                failures.append(f"{link}: beacon is '{e['beacon']}', should be '{BEACON_OF[link]}'")
            if e["rate"] is None and e["rate_text"] != UNMEASURED:
                failures.append(f"{link}: can't read rate '{e['rate_text']}' (write a bare number)")
        rate = lowest(entries)
        if rate is None:
            if all(e["rate_text"] == UNMEASURED for e in entries):
                failures.append(f"{link}: not yet measured")
        elif rate < min_rate:
            share = rate / events_hz(LINKS[link]["tx"])
            failures.append(f"{link}: rate {rate:.1f} < {min_rate:.1f} adverts/s ({share:.0%} of its beacon's events)")
    return failures


def warnings(rows: dict[str, list[dict]]) -> list[str]:
    """Rows whose hand-written Result disagrees with their rate. These don't change the verdict."""
    out = []
    for link, entries in rows.items():
        for e in entries:
            if e["rate"] is None or e["result"] not in ("PASS", "FAIL"):
                continue
            should = "PASS" if e["rate"] >= MIN_RATES[link] else "FAIL"
            if e["result"] != should:
                out.append(f"{link}: row with {e['rate']:.1f}/s says {e['result']}, the rate says {should}")
    return out


def main() -> None:
    if not GATE_PATH.exists():
        print("radio/GATE.md not found.", file=sys.stderr)
        sys.exit(1)
    rows = parse_gate2_md(GATE_PATH.read_text(encoding="utf-8"))
    for w in warnings(rows):
        print(f"warning: {w}", file=sys.stderr)
    failures = check(rows)
    if failures:
        print("GATE 2 FAIL")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    summary_str = ", ".join(f"{b}: {lowest(rows[b]):.1f}/s" for b in MIN_RATES)
    print(f"GATE 2 PASS (lowest of each: {summary_str})")


if __name__ == "__main__":
    main()
