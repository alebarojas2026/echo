"""The hall paths: the simulated link and the three quiet-level rules (SIMULATED data)."""
import numpy as np

from lab import hall


def test_an_empty_hall_is_quiet_and_a_crossing_shows():
    t, dbm, crossings = hall.simulate(1, 0, 0.0, 15.0)
    assert len(crossings) >= 10 and 4 < len(t) / hall.T_S < 9
    quiet = np.std(dbm[(t > 20_000) & (t < 50_000)])
    c = crossings[3] * 1000
    assert dbm[(t > c - 700) & (t < c + 700)].min() < np.median(dbm) - 3 * max(quiet, 0.5)


def test_a_full_hall_hides_one_walker_from_the_links_own_quiet_level():
    quiet = hall.session(seed=2, people=0)
    full = hall.session(seed=2, people=200)
    assert quiet["own"]["hit"] > quiet["own"]["false"] + 0.3
    assert full["quiet_own_db"] > 1.5 * quiet["quiet_own_db"]          # the quiet level has learned the crowd
    assert full["own"]["hit"] < 0.4                                    # ... so the walker no longer shows
    assert full["empty"]["on_frac"] > 0.5 and full["busy_frac"] > 0.5  # against the empty hall it is always "moving"
