"""Gate-1 Wi-Fi report helper.

Reads ``radio/GATE.md`` run-result lines and prints a pass/fail summary.

Usage (on the board, after a live run):
    python -m radio.report_wifi

Gate 1 has one table per Wi-Fi link in radio/nodes.json, each under a `### <link id>` heading
(the board's pi5>unoq:wifi, and Pi B's pi5>pi5b:wifi in the desk layout). A table for a link
nodes.json doesn't have is ignored, so GATE.md can carry the next layout's rows early. With no
such heading at all, the whole Gate 1 section is the first Wi-Fi link's.

The script is also imported by the pytest suite to verify that GATE.md rows
are well-formed once Alexander fills them in.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from .nodes import LINKS

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
            run = row["run"]
            if "__" in (row["baseline"], row["blocked"]):
                failures.append(f"run {run}: not yet measured")
                continue
            # The drop is worked out from the two dBm cells, so a typo or a sign slip can't pass.
            drop = float(row["baseline"]) - float(row["blocked"])
            if drop < 3.0:
                failures.append(f"run {run}: drop {drop:g} dB < 3 dB")
            if row["drop"] == "__" or abs(float(row["drop"]) - drop) > 0.5:
                failures.append(f"run {run}: Drop cell {row['drop']} isn't "
                                f"{row['baseline']} - ({row['blocked']}) = {drop:g} dB")
            if row["result"].upper() != "PASS":
                failures.append(f"run {run}: Result is {row['result']}")
    return failures


WIFI_LINKS = [link_id for link_id, link in LINKS.items() if link["kind"] == "wifi"]
_HEADING = re.compile(r"^#{2,3}\s.*$", re.M)


def gate1_section(text: str) -> str:
    """The text under '## Gate 1', up to the next '## ' heading (all of it if there's none)."""
    m = re.search(r"^##\s*Gate 1\b.*?$(?P<body>.*?)(?=^##\s|\Z)", text, re.M | re.S)
    return m.group("body") if m else text


def tables(text: str, links=None) -> dict[str, str]:
    """{wifi link: the text under its '### <link>' heading} for each link in `links` that has one.

    With no such heading in Gate 1, the whole section belongs to the first link (the old layout).
    """
    links = WIFI_LINKS if links is None else links
    body = gate1_section(text)
    heads = list(_HEADING.finditer(body))
    found = {}
    for i, head in enumerate(heads):
        named = [link for link in links if link in head.group(0) and head.group(0).startswith("###")]
        if named:
            end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
            found[named[0]] = body[head.end():end]
    if not found and links and not any(h.group(0).startswith("###") and ":wifi" in h.group(0) for h in heads):
        found[links[0]] = body
    return found


def report(text: str, links=None) -> tuple[bool, list[str]]:
    """(passed, lines): every wifi link's table checked on its own."""
    links = WIFI_LINKS if links is None else links
    found = tables(text, links)
    failures, done = [], []
    for link in links:
        if link not in found:
            failures.append(f"{link}: no Gate 1 table (a '### {link}' heading)")
            continue
        data = parse_gate_md(found[link])
        failures += [f"{link}: {f}" for f in check(data)]
        done.append(f"{link} {data['rate_hz']} samples/s")
    if failures:
        return False, ["GATE 1 FAIL"] + [f"  - {f}" for f in failures]
    return True, [f"GATE 1 PASS  ({', '.join(done)}; 3/3 runs >= 3 dB drop on each)"]


def main() -> None:
    if not GATE_PATH.exists():
        print("radio/GATE.md not found.", file=sys.stderr)
        sys.exit(1)
    passed, lines = report(GATE_PATH.read_text(encoding="utf-8"))
    print("\n".join(lines))
    if not passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
