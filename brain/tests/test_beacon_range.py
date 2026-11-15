"""A rough range for an unplaced beacon (brain/beacon_range.py), on synthetic readings.

These test the arithmetic and the "unknown" rules. They say nothing about how well signal
strength gives distance in a real hall.
"""
import random

from brain import beacon_range as R

T0 = 1_763_149_500_000


def heard(ranges, beacon, receiver, level, seconds=12, hz=4, noise=2.0, seed=0, t0=T0):
    rng = random.Random(f"{receiver}-{seed}")
    for i in range(int(seconds * hz)):
        ranges.add(beacon, receiver, t0 + round(i * 1000 / hz), round(level + rng.gauss(0, noise)))
    return t0 + seconds * 1000


def test_the_model_is_the_plain_log_distance_one():
    assert R.metres(-59) == 1.0 and round(R.metres(-84), 1) == 10.0          # n = 2.5: 25 dB is ten times as far
    assert round(R.metres(-79, 2.0), 1) == 10.0 and round(R.metres(-89, 3.0), 1) == 10.0


def test_a_steady_beacon_gets_a_range_with_its_width_and_its_assumptions():
    ranges = R.Ranges()
    for rx, level in (("unoq", -84), ("pi5", -86), ("pi5b", -83)):
        now = heard(ranges, "h", rx, level)
    est = ranges.estimate("h", now)
    assert 8 <= est["m"] <= 13 and est["lo_m"] < est["m"] < est["hi_m"]
    assert est["hi_m"] / est["lo_m"] >= 2                                    # honest: the far end is over twice the near end
    assert est["from"] == ["pi5", "pi5b", "unoq"]
    assert est["assumes"] == {"at_1m_dbm": -59.0, "exponent": [2.0, 3.0]}
    assert set(est) == {"m", "lo_m", "hi_m", "from", "assumes"}              # a range only: no position, no bearing
    stronger = R.Ranges()
    now2 = heard(stronger, "h", "unoq", -70)
    assert stronger.estimate("h", now2)["m"] < est["m"]                      # stronger means nearer


def test_it_does_not_jump_with_single_readings():
    ranges = R.Ranges()
    now = heard(ranges, "h", "unoq", -84, seconds=30, noise=3.0)
    ests = []
    for i in range(40):                                                      # ten more seconds with a few wild readings
        now += 250
        ranges.add("h", "unoq", now, -84 + (15 if i % 9 == 0 else random.Random(i).gauss(0, 3)))
        ests.append(ranges.estimate("h", now)["m"])
    assert max(ests) / min(ests) < 1.5


def test_unknown_until_there_are_ten_seconds_of_readings_and_again_when_they_stop():
    ranges = R.Ranges()
    assert ranges.estimate("h", T0) is None                                  # never heard
    now = heard(ranges, "h", "unoq", -84, seconds=5)
    assert ranges.estimate("h", now) is None                                 # 5 s is not enough
    now = heard(ranges, "h", "unoq", -84, seconds=12)
    assert ranges.estimate("h", now) is not None
    assert ranges.estimate("h", now + 8_000) is None                         # it went quiet: no old guess is kept
    sparse = R.Ranges()
    now = heard(sparse, "j", "unoq", -84, seconds=12, hz=0.5)                # 6 readings in 12 s
    assert sparse.estimate("j", now) is None


def test_unknown_when_the_readings_disagree():
    apart = R.Ranges()
    now = heard(apart, "h", "unoq", -70)
    heard(apart, "h", "pi5", -90)                                            # receivers a metre apart, 20 dB apart
    assert apart.estimate("h", now) is None
    wild = R.Ranges()
    now = heard(wild, "h", "unoq", -80, noise=12.0)                          # one receiver, swinging all over
    assert wild.estimate("h", now) is None
    mixed = R.Ranges()
    now = heard(mixed, "h", "unoq", -84)
    heard(mixed, "h", "pi5", -80, noise=12.0)                                # the wild one is left out, the steady one used
    assert mixed.estimate("h", now)["from"] == ["unoq"]


def test_beacons_are_kept_apart_and_the_far_end_is_capped():
    ranges = R.Ranges()
    now = heard(ranges, "h", "unoq", -70)
    heard(ranges, "j", "unoq", -99)
    near, far = ranges.estimate("h", now), ranges.estimate("j", now)
    assert near["m"] < 5 and far["m"] > 30 and far["hi_m"] == R.MAX_M
