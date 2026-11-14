"""Gate-2 Bluetooth raw scan report helper.

Reads the Gate 2 table in ``radio/GATE.md`` and prints a pass/fail summary.

Usage (on the board, after a live run):
    python -m radio.report_hci

Pass criteria (the lowest rate written for each link):
    pi5>unoq:ble:                  >= 20 adverts/s
    east>unoq:ble, west>unoq:ble:  >= 7 adverts/s
    east>pi5:ble, west>pi5:ble:    >= 7 adverts/s

The verdict comes from the rates alone. One row per run is fine: the lowest one counts.
The Result column is only cross-checked, so it can stay `__`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

GATE_PATH = Path(__file__).resolve().parent / "GATE.md"

MIN_RATES: dict[str, float] = {
    "pi5>unoq:ble": 20.0,
    "east>unoq:ble": 7.0,
    "west>unoq:ble": 7.0,
    "east>pi5:ble": 7.0,
    "west>pi5:ble": 7.0,
}
BEACON_OF = {link: {"pi5": "S", "east": "E", "west": "W"}[link.split(">")[0]] for link in MIN_RATES}
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
            failures.append(f"{link}: rate {rate:.1f} < {min_rate:.1f} adverts/s")
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
