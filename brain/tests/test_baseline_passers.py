"""People walking past the camera, outside the layout, don't stop a baseline from finishing (#575)."""
from brain.core import BASELINE_MS, Brain
from brain.tests.simdata import T0_MS


def run(seconds, in_view, present=lambda s: False, dbm=lambda s, link: -55, brain=None):
    """10 Hz of cam, label and one reading per link. in_view(s) = somebody is in the camera's frame.
    Returns (brain, seconds at which baseline_done came, or None)."""
    b = brain or Brain()
    if brain is None:
        b.on_cmd({"v": 2, "type": "cmd", "cmd": "baseline", "args": {}})
    done, seq = None, 0
    for i in range(int(seconds * 10)):
        s, t = i / 10, T0_MS + i * 100
        seen = bool(in_view(s))
        msgs = [{"type": "cam", "state": "on", "fps": 9},
                {"type": "label", "frame": i, "mode": "off", "persons_in_frame": int(seen),
                 "present": seen and bool(present(s)), "zone": 0, "foot_m": None, "motion": None,
                 "conf": 0.9, "clipped": False}]
        msgs += [{"type": "rssi", "link": link, "kind": link.split(":")[1], "tx": link.split(">")[0],
                  "rx": link.split(">")[1].split(":")[0], "dbm": dbm(s, link)} for link in b.links]
        for m in msgs:
            seq += 1
            b.on_message({"v": 2, "t": t, "seq": seq, "src": "sim", "recv_t": t, **m})
        b.state()
        if done is None and any(e["kind"] == "baseline_done" for e in b.pop_events()):
            done = s
    return b, done


def every_8_s(s):          # a passer-by crosses the camera's view for 1.5 s, every 8 s
    return (s * 10) % 80 < 15


def test_with_nobody_around_it_takes_20_s():
    _, done = run(40, lambda s: False)
    assert 20 <= done <= 20.5


def test_passers_by_only_pause_it():
    b, done = run(90, every_8_s)                     # the issue's repro: never finished in 90 s before
    assert done is not None and done <= 20 + 4 * 1.5 + 2
    assert len(b.base) == len(b.links)


def test_readings_taken_while_somebody_passes_are_left_out():
    passing = lambda s: 5 <= s < 7
    b, done = run(40, passing, dbm=lambda s, link: -70 if 5 <= s < 7.1 else -55)   # the links dip while they pass
    assert done is not None and set(b.base.values()) == {-55.0}
    assert all(abs(hz - 10) <= 0.6 for hz in b.expected_hz.values())                 # 20 s of clean readings


def test_somebody_inside_the_layout_starts_the_20_s_again():
    stepped_in = lambda s: 10 <= s < 11
    _, done = run(60, stepped_in, present=lambda s: True)
    assert 31 <= done <= 31.6                        # 20 s from when they left, not 20 s in total


def test_somebody_who_stays_in_view_starts_it_again():
    lingers = lambda s: 10 <= s < 16                 # over 3 s in view, outside the layout
    _, done = run(60, lingers)
    assert 36 <= done <= 36.6


def test_a_passer_before_the_capture_starts_just_delays_it():
    _, done = run(60, lambda s: s < 2)
    assert 22 <= done <= 22.6
