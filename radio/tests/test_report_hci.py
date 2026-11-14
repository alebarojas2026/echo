"""Tests for radio.report_hci."""

import pytest
from radio.report_hci import parse_gate2_md, check

PASSING_MD = """
## Gate 2 — Bluetooth raw scan (#20)

**Pass criteria:** Pi beacon ≥ 20 adverts/s; each phone beacon ≥ 7 adverts/s.

| Beacon | Node ID | Adverts/s | Result |
|--------|---------|-----------|--------|
| pi5    | S       | 25.4      | PASS   |
| east   | E       | 8.2       | PASS   |
| west   | W       | 7.5       | PASS   |

**Overall Gate 2:** PASS
"""

FAILING_PI_RATE_MD = """
## Gate 2 — Bluetooth raw scan (#20)

| Beacon | Node ID | Adverts/s | Result |
|--------|---------|-----------|--------|
| pi5    | S       | 18.0      | FAIL   |
| east   | E       | 8.0       | PASS   |
| west   | W       | 8.0       | PASS   |
"""

FAILING_PHONE_RATE_MD = """
## Gate 2 — Bluetooth raw scan (#20)

| Beacon | Node ID | Adverts/s | Result |
|--------|---------|-----------|--------|
| pi5    | S       | 22.0      | PASS   |
| east   | E       | 5.1       | FAIL   |
| west   | W       | 7.0       | PASS   |
"""

UNMEASURED_MD = """
## Gate 2 — Bluetooth raw scan (#20)

| Beacon | Node ID | Adverts/s | Result |
|--------|---------|-----------|--------|
| pi5    | S       | __        | __     |
| east   | E       | __        | __     |
| west   | W       | __        | __     |
"""

MISSING_BEACON_MD = """
## Gate 2 — Bluetooth raw scan (#20)

| Beacon | Node ID | Adverts/s | Result |
|--------|---------|-----------|--------|
| pi5    | S       | 25.0      | PASS   |
| east   | E       | 8.0       | PASS   |
"""


def test_parse_passing_rows():
    rows = parse_gate2_md(PASSING_MD)
    assert len(rows) == 3
    assert rows["pi5"]["rate"] == pytest.approx(25.4)
    assert rows["east"]["rate"] == pytest.approx(8.2)
    assert rows["west"]["rate"] == pytest.approx(7.5)
    assert rows["pi5"]["result"] == "PASS"


def test_passing_gate():
    rows = parse_gate2_md(PASSING_MD)
    assert check(rows) == []


def test_failing_pi_rate():
    rows = parse_gate2_md(FAILING_PI_RATE_MD)
    failures = check(rows)
    assert any("pi5" in f and "18.0 < 20.0" in f for f in failures)


def test_failing_phone_rate():
    rows = parse_gate2_md(FAILING_PHONE_RATE_MD)
    failures = check(rows)
    assert any("east" in f and "5.1 < 7.0" in f for f in failures)


def test_unmeasured():
    rows = parse_gate2_md(UNMEASURED_MD)
    failures = check(rows)
    assert len(failures) == 3
    assert all("not yet measured" in f for f in failures)


def test_missing_beacon():
    rows = parse_gate2_md(MISSING_BEACON_MD)
    failures = check(rows)
    assert any("west" in f and "not found" in f for f in failures)
