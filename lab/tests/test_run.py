"""The whole session runs through the real brain and scores (SIMULATED data)."""
from lab import run


def test_smoke_session_trains_and_scores():
    out = run.session(seed=0, smoke=True, replays=False)
    m = out["metrics"]
    assert m["trained"] and m["heldout_windows"] > 0
    assert 0.0 <= m["heldout_acc"] <= 1.0
