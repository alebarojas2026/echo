"""A jump in the board's clock neither blocks the loop nor stops decisions (#615)."""
import time
import tracemalloc

import pytest

from brain import features as F
from brain.core import Brain


def rssi(t, link="pi5>unoq:wifi", dbm=-55):
    return {"type": "rssi", "recv_t": t, "link": link, "dbm": dbm}


def feed(w, t0, seconds):
    """10 readings a second for `seconds`; returns the windows closed."""
    out = []
    for i in range(int(seconds * 10)):
        out += w.push(rssi(t0 + i * 100))
    return out


def test_a_jump_forward_closes_a_handful_of_windows_not_thousands():
    w = F.Windower({"pi5>unoq:wifi": -50})
    feed(w, 1_000_000, 5)
    tracemalloc.start()
    t0 = time.perf_counter()
    closed = w.push(rssi(1_000_000 + 5_000 + 2 * 24 * 3_600_000))        # two days ahead
    took, peak = time.perf_counter() - t0, tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert closed == [] and w.restarts == 1
    assert took < 0.05 and peak < 1 * 2**20                               # before: seconds, and GBs on the board
    after = feed(w, 1_000_000 + 5_100 + 2 * 24 * 3_600_000, 3)
    assert len(after) >= 15 and all(x["links"]["pi5>unoq:wifi"]["n"] >= 1 for x in after)


@pytest.mark.parametrize("back_ms", [60_000, 3_600_000, 2 * 24 * 3_600_000])
def test_a_jump_back_does_not_stop_the_windows(back_ms):
    w = F.Windower({"pi5>unoq:wifi": -50})
    feed(w, 10**12, 5)
    after = feed(w, 10**12 + 5_000 - back_ms, 3)                          # the clock is set back
    assert w.restarts == 1 and len(after) >= 15                           # windows again within about a second
    assert after[0]["end"] < 10**12 and after[-1]["links"]["pi5>unoq:wifi"]["n"] == 10
    # Readings from before the jump are not mixed into the windows after it.
    assert all(x["start"] >= 10**12 + 5_000 - back_ms - 100 for x in after)


def test_forward_and_then_back_again_recovers_both_times():
    w = F.Windower({"pi5>unoq:wifi": -50})
    feed(w, 10**12, 3)
    assert len(feed(w, 10**12 + 2 * 24 * 3_600_000, 3)) >= 15
    assert len(feed(w, 10**12 + 720_000, 3)) >= 15 and w.restarts == 2    # back to the right time 12 min later


def test_ordinary_gaps_and_small_steps_are_untouched():
    w = F.Windower({"pi5>unoq:wifi": -50})
    feed(w, 1_000_000, 3)
    closed = w.push(rssi(1_000_000 + 3_000 + 4_000))                      # a 4 s silence: stepped through as before
    assert len(closed) == 41 and w.restarts == 0
    w.push(rssi(1_000_000 + 6_500))                                       # 0.5 s late (reordered): no restart
    assert w.restarts == 0


def test_the_brain_keeps_deciding_across_a_jump_back():
    b = Brain(clock=None)
    b._set_baseline({link: -50.0 for link in b.links}, {link: 15.0 for link in b.links})
    t = 10**12

    def tick(t):
        for link in b.links:
            b.on_message({"v": 2, "type": "rssi", "t": t, "seq": 1, "src": "sim", "link": link, "dbm": -55,
                          "recv_t": t})

    for i in range(50):
        t += 100
        tick(t)
    t -= 60_000                                                           # a minute back
    ends = []
    for i in range(100):                                                  # 10 s of readings after it
        t += 100
        tick(t)
        ends.append(b.window["end"])
    assert ends[-1] - ends[20] >= 7_000                                   # the window moves with the feed again
