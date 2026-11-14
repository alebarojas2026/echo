"""Gate-1 Wi-Fi report helper.

Reads ``radio/GATE.md`` run-result lines and prints a pass/fail summary.

Usage (on the board, after a live run):
    python -m radio.report_wifi

The script is also imported by the pytest suite to verify that GATE.md rows
are well-formed once Alexander fills them in.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

GATE_PATH = Path(__file__).resolve().parent / "GATE.md"

# A filled row looks like:
#   | 1 | -62 | -67 | 5 | PASS |
# or unmeasured:
#   | 1 | __  | __  | __ | __ |
_ROW_RE = re.compile(
    r"\|\s*(?P<run>\d+)\s*\|"
    r"\s*(?P<baseline>-?\d+(?:\.\d+)?|__)\s*\|"
    r"\s*(?P<blocked>-?\d+(?:\.\d+)?|__)\s*\|"
    r"\s*(?P<drop>-?\d+(?:\.\d+)?|__)\s*\|"
    r"\s*(?P<result>PASS|FAIL|__)\s*\|",
    re.IGNORECASE,
)
_RATE_RE = re.compile(
    r"Measured sample rate[\s:*]+(?P<rate>\d+(?:\.\d+)?)\s*samples/s",
    re.IGNORECASE,
)


def parse_gate_md(text: str) -> dict:
    """Return parsed gate-1 data: rate and per-run rows."""
    rate_match = _RATE_RE.search(text)
    rate = float(rate_match.group("rate")) if rate_match else None
    rows = [m.groupdict() for m in _ROW_RE.finditer(text)]
    return {"rate_hz": rate, "rows": rows}


def check(data: dict) -> list[str]:
    """Return a list of failure reasons, empty means PASS."""
    failures: list[str] = []
    rate = data.get("rate_hz")
    if rate is None:
        failures.append("measured sample rate not recorded in GATE.md")
    elif rate < 20:
        failures.append(f"rate {rate} < 20 samples/s")

    rows = data.get("rows", [])
    if len(rows) < 3:
        failures.append(f"only {len(rows)} run(s) recorded; need 3")
    else:
        for row in rows[:3]:
            if row["result"].strip().upper() == "__" or row["drop"].strip() == "__":
                failures.append(f"run {row['run']}: not yet measured")
                continue
            drop = float(row["drop"])
            if drop < 3.0:
                failures.append(f"run {row['run']}: drop {drop} dB < 3 dB")
    return failures


def main() -> None:
    if not GATE_PATH.exists():
        print("radio/GATE.md not found.", file=sys.stderr)
        sys.exit(1)
    text = GATE_PATH.read_text(encoding="utf-8")
    data = parse_gate_md(text)
    failures = check(data)
    if failures:
        print("GATE 1 FAIL")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print(f"GATE 1 PASS  ({data['rate_hz']} samples/s, 3/3 runs >= 3 dB drop)")


if __name__ == "__main__":
    main()
