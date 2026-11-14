"""Gate-2 Bluetooth raw scan report helper.

Reads ``radio/GATE.md`` beacon scan lines and prints a pass/fail summary.

Usage (on the board, after a live run):
    python -m radio.report_hci

Pass criteria:
    pi5:  >= 20 adverts/s
    east: >= 7 adverts/s
    west: >= 7 adverts/s
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

GATE_PATH = Path(__file__).resolve().parent / "GATE.md"

# A filled or unmeasured row:
# | pi5    | S       | 24.1      | PASS   |
# | east   | E       | __        | __     |
_ROW_RE = re.compile(
    r"\|\s*(?P<beacon>pi5|east|west)\s*\|"
    r"\s*(?P<node_id>[SEW])\s*\|"
    r"\s*(?P<rate>\d+(?:\.\d+)?|__)\s*\|"
    r"\s*(?P<result>PASS|FAIL|__)\s*\|",
    re.IGNORECASE,
)

MIN_RATES: dict[str, float] = {
    "pi5": 20.0,
    "east": 7.0,
    "west": 7.0,
}


def parse_gate2_md(text: str) -> dict[str, dict]:
    """Return parsed Gate-2 rows mapped by beacon name."""
    rows: dict[str, dict] = {}
    for m in _ROW_RE.finditer(text):
        d = m.groupdict()
        beacon = d["beacon"].lower()
        rate_str = d["rate"].strip()
        rate = float(rate_str) if rate_str != "__" else None
        rows[beacon] = {
            "beacon": beacon,
            "node_id": d["node_id"],
            "rate": rate,
            "result": d["result"].strip().upper(),
        }
    return rows


def check(rows: dict[str, dict]) -> list[str]:
    """Return a list of failure reasons, empty means PASS."""
    failures: list[str] = []
    for beacon, min_rate in MIN_RATES.items():
        if beacon not in rows:
            failures.append(f"beacon '{beacon}' not found in Gate 2 table")
            continue
        entry = rows[beacon]
        rate = entry["rate"]
        if rate is None or entry["result"] == "__":
            failures.append(f"beacon '{beacon}': not yet measured")
        elif rate < min_rate:
            failures.append(f"beacon '{beacon}': rate {rate:.1f} < {min_rate:.1f} adverts/s")
    return failures


def main() -> None:
    if not GATE_PATH.exists():
        print("radio/GATE.md not found.", file=sys.stderr)
        sys.exit(1)
    text = GATE_PATH.read_text(encoding="utf-8")
    rows = parse_gate2_md(text)
    failures = check(rows)
    if failures:
        print("GATE 2 FAIL")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        summary_str = ", ".join(f"{b}: {r['rate']:.1f}/s" for b, r in sorted(rows.items()))
        print(f"GATE 2 PASS ({summary_str})")


if __name__ == "__main__":
    main()
