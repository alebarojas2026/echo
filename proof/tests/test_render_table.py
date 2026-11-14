import copy

import pytest

from proof.render_table import render


DOCUMENT = """# Proof

| Number | Value | Method | N | Date | Commit |
|---|---|---|---|---|---|
| Zone accuracy (radio vs camera agreement) | pending | held-out sessions | 3+ people planned | | |
| Person vs object accuracy | pending | box then person | 10+ trials planned | | |
| Time per decision | pending | decision step | 1,000+ planned | | |
| End-to-end update latency | pending | measured video method | 10 planned | | |
| Board power draw | pending | power meter | 1 each planned | | |

## Honest limits
Unchanged prose.
"""


def report():
    return dict(zone=dict(correct=8, total=10, ci95=[0.5, 1], sessions=["s1", "s2"], walkers=2,
                          method="held-out"), threshold_zone=dict(correct=6, total=10),
                person_vs_object=dict(correct=None, total=None), train_s=None,
                ms_per_decision=dict(p50=2, p95=4), watts=dict(idle=None),
                false_alarms_per_min=0, bytes_out=None, images_stored=None, models_on_board=None,
                measured_at="2026-11-14T20:00:00+00:00", commit="abc1234")


def test_measured_values_and_provenance():
    output = render(DOCUMENT, report())
    assert "8/10 (80.0%); 95% CI 50.0–100.0%" in output
    assert "10 decisions; 2 sessions; 2 walkers" in output
    assert "p50 2 ms; p95 4 ms" in output
    assert "| False presence episodes per minute | 0 |" in output
    assert "| Person vs object accuracy | __ |" in output
    assert "Unchanged prose." in output and "abc1234" in output
    assert "| End-to-end update latency | __ | measured video method | __ | __ | __ |" in output


def test_idempotent_and_does_not_mutate_report():
    data = report()
    before = copy.deepcopy(data)
    once = render(DOCUMENT, data)
    assert render(once, data) == once
    assert data == before


def test_missing_values_never_invented():
    output = render(DOCUMENT, {})
    assert "| Zone accuracy (radio vs camera agreement) | __ |" in output
    assert "| Images stored | __ |" in output
    assert "pending" not in output and "planned" not in output


@pytest.mark.parametrize("change", [
    {"commit": None}, {"measured_at": None}, {"train_s": -1},
    {"zone": {"correct": 11, "total": 10}},
    {"zone": {"correct": 8, "total": 10, "ci95": [0.8, 0.2]}},
    {"zone": {"method": "SYNTHETIC SELF-TEST"}},
])
def test_invalid_or_synthetic_proof_rejected(change):
    data = report()
    data.update(change)
    with pytest.raises(ValueError):
        render(DOCUMENT, data)


def test_measurement_method_cannot_break_markdown():
    output = render(DOCUMENT, report())
    assert all(len(line.split("|")) == 8 for line in output.splitlines() if line.startswith("|"))


def test_escaped_method_pipes_stay_idempotent():
    document = DOCUMENT.replace("held-out sessions", "held-out \\| sessions")
    output = render(document, report())
    assert render(output, report()) == output
