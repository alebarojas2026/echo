"""Baselines at the reading rates measured on the kit (#634): 7 to 13 a second, one link at 1.7, uneven."""
import random

from brain.core import Brain
from brain.tests.simdata import T0_MS

SLOW = "west>pi5:ble"


def feed(brain, seconds, rate, seed, silent=lambda link, s: False):
    """Readings at random arrival times (rate(link) a second on average), with cam and labels at 10 Hz.
    Returns the seconds at which baseline_done came, or None."""
    rng = random.Random(seed)
    events = []
    for link in brain.links:
        t = 0.0
        while t < seconds:
            t += rng.expovariate(rate(link))
            if not silent(link, t):
                events.append((t, {"type": "rssi", "link": link, "kind": link.split(":")[1], "tx": link.split(">")[0],
                                   "rx": link.split(">")[1].split(":")[0], "dbm": -55 + rng.choice((-1, 0, 0, 1))}))
    for i in range(int(seconds * 10)):
        events.append((i / 10, {"type": "cam", "state": "on", "fps": 9}))
        events.append((i / 10, {"type": "label", "frame": i, "mode": "off", "persons_in_frame": 0, "present": False,
                                "zone": 0, "foot_m": None, "motion": None, "conf": 0.9, "clipped": False}))
    done, next_state = None, 0.0
    for seq, (s, m) in enumerate(sorted(events, key=lambda e: e[0])):
        t = T0_MS + int(s * 1000)
        brain.on_message({"v": 2, "t": t, "seq": seq, "src": "sim", "recv_t": t, **m})
        if s >= next_state:
            next_state = s + 0.1
            brain.state()
            if done is None and any(e["kind"] == "baseline_done" for e in brain.pop_events()):
                done = s
    return done


def kit(link):
    return 1.7 if link == SLOW else 8.0


def test_a_plain_baseline_finishes_with_one_link_at_1_7_a_second():
    for seed in range(5):
        brain = Brain()
        brain.on_cmd({"v": 2, "type": "cmd", "cmd": "baseline", "args": {}})
        done = feed(brain, 60, kit, seed)
        assert done is not None and done <= 45, seed            # before: never in 120 s. A chance 3 s gap can start it again once
        assert 1.0 <= brain.expected_hz[SLOW] <= 2.5 and len(brain.base) == len(brain.links)


def test_all_links_at_7_a_second_finish_first_time():
    for seed in range(5):
        brain = Brain()
        brain.on_cmd({"v": 2, "type": "cmd", "cmd": "baseline", "args": {}})
        done = feed(brain, 40, lambda link: 7.0, seed)
        assert done is not None and done <= 21.5, seed


def test_a_link_silent_for_over_3_s_still_starts_the_20_s_again():
    brain = Brain()
    brain.on_cmd({"v": 2, "type": "cmd", "cmd": "baseline", "args": {}})
    done = feed(brain, 60, lambda link: 8.0, 1, silent=lambda link, s: link == SLOW and 5 <= s < 10)
    assert done is not None and 29.5 <= done <= 32
