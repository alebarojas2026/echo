"""Fixed dB numbers against a link's own quiet level (#641, the measured spreads on #95).

Measured on the kit with nobody there: the std of the 0.5 s means is about 0.2 dB on the Wi-Fi
links and 1 to 3 dB on the Bluetooth links. Three rules compare against a fixed number that a
Bluetooth link can't meet; each can be told to give way to a multiple of the link's own quiet
level. All three are off by default: the contract's numbers alone."""
import json
import random

import numpy as np
import pytest

from brain import features as F
from brain import settings as S
from brain.alert import CHECKIN_LINK, CheckIn
from brain.core import Brain
from brain.health import Health
from brain.tests.test_alert import T0, wave
from brain.tests.test_core import Feed, cmd

WIFI, BLE = "pi5>unoq:wifi", "east>unoq:ble"


def capture(seconds=20, seed=0):
    """An empty baseline capture at the measured rates: Wi-Fi 23 a second and quiet, Bluetooth 6 a
    second with 3 dB of wobble that moves its 0.5 s means about."""
    rng, out = random.Random(seed), []
    for link, hz, fast, slow in ((WIFI, 23, 0.4, 0.1), (BLE, 6, 2.5, 1.6)):
        t, drift = 0.0, 0.0
        while t < seconds * 1000:
            if int(t // 500) != int((t - 1000 / hz) // 500):
                drift = rng.gauss(0, slow)
            out.append({"type": "rssi", "recv_t": int(t), "link": link, "dbm": round(-50 + drift + rng.gauss(0, fast))})
            t += 1000 / hz
    return sorted(out, key=lambda m: m["recv_t"])


def test_the_quiet_level_is_the_std_of_the_half_second_means_over_the_capture():
    quiet = F.quiet(capture())
    assert quiet[WIFI] < 0.4 and 1.2 < quiet[BLE] < 3.0
    assert F.quiet([{"type": "rssi", "recv_t": 0, "link": "x", "dbm": -50}]) == {}   # one bin: nothing to measure


def body_on_the_line(hm, seconds=12, quiet=2.0, seed=0, thrash=0.0):
    """A torso steps onto a Bluetooth line with the model saying nobody: 12 dB down, wobbling as it
    does empty (the 0.5 s means move by `quiet` dB). thrash: the level also flips by this much
    every half second, as a failing radio would. Returns the last health dict."""
    rng, out, drift = np.random.default_rng(seed), None, 0.0
    for i in range(seconds * 10):
        now = 1000 + i * 100
        if i % 5 == 0:
            drift = rng.normal(0, quiet) - (thrash if (i // 5) % 2 else 0)
        hm.add(WIFI, now, -50)
        if i % 2 == 0:                               # 5 readings a second
            hm.add(BLE, now, round(-50 - (12 if i >= 20 else 0) + drift + rng.normal(0, 1.0)))
        out = hm.update(now, "none")
    return out["health"]


def test_a_body_drop_on_a_noisy_link_reads_as_a_jump_on_0_8_dB_and_as_steady_on_its_own_quiet_level():
    def health():
        return Health([WIFI, BLE], {WIFI: 10.0, BLE: 5.0}, {WIFI: -50.0, BLE: -50.0})

    fixed = health()
    assert body_on_the_line(fixed) == {"status": "blind", "blind": [BLE], "reason": "jump"}   # today: SENSOR BLIND

    own = health()
    own.set_quiet({WIFI: 0.2, BLE: 2.0}, 1.5)
    assert own.links[BLE].steady_db == 3.0 and own.links[WIFI].steady_db == 0.8   # never under the contract's 0.8
    assert body_on_the_line(own)["status"] == "ok"

    off = health()
    off.set_quiet({WIFI: 0.2, BLE: 2.0}, 0)          # the setting at its default: nothing changes
    assert off.links[BLE].steady_db == 0.8 and body_on_the_line(off)["status"] == "blind"


def test_a_link_thrown_about_far_beyond_its_quiet_level_is_still_a_jump():
    hm = Health([WIFI, BLE], {WIFI: 10.0, BLE: 5.0}, {WIFI: -50.0, BLE: -50.0})
    hm.set_quiet({BLE: 2.0}, 1.5)
    assert body_on_the_line(hm, quiet=0.5, thrash=12.0)["status"] == "blind"


def test_the_check_in_can_let_a_noisy_link_wobble_by_its_own_measure():
    """A Bluetooth link whose 0.5 s means move about 2.5 dB with nobody near (measured: 1 to 3)."""
    def noisy(seed):
        rng, held = random.Random(seed), [0.0]

        def level(i):
            if i % 7 == 0:
                held[0] = rng.gauss(0, 2.5)
            return -58 + held[0] + rng.gauss(0, 0.5)
        return level

    def waves_seen(limit):
        seen = 0
        for seed in range(40):
            rule = CheckIn()
            rule.other_db_of = {"east>unoq:ble": limit}
            seen += bool(wave(rule, T0, other=noisy(seed)))
        return seen

    assert waves_seen(0) <= 20                       # on 3 dB alone: half the waves or more are refused
    assert waves_seen(4 * 2.5) >= 38                 # checkin_x_quiet 4 on a quiet level of 2.5 dB
    rule = CheckIn()
    rule.other_db_of = {"east>unoq:ble": 10.0}
    assert not wave(rule, T0, other=lambda i: -58 - (14 if i > 18 else 0))   # a body stepping onto it still blocks


def test_a_baseline_measures_the_quiet_level_writes_it_and_reads_it_back(tmp_path):
    brain = Brain(sessions_dir=tmp_path, settings=S.DEFAULT.with_(steady_x_quiet=1.5, checkin_x_quiet=4, settle_x_quiet=2))
    brain.on_cmd(cmd("baseline"))
    Feed(brain).play("empty_room", seed=1)
    assert set(brain.quiet_db) == set(brain.links) and all(0 < q < 2 for q in brain.quiet_db.values())
    doc = json.loads((tmp_path / "baseline.json").read_text())
    assert all(set(v) == {"base_dbm", "expected_hz", "quiet_db"} for v in doc["links"].values())
    again = Brain(sessions_dir=tmp_path, settings=brain.settings)
    assert again.quiet_db == {k: v["quiet_db"] for k, v in doc["links"].items()}
    link = again.links[1]
    again.quiet_db[link] = 2.0
    again._set_baseline(again.base, again.expected_hz, again.quiet_db)
    assert again.health.links[link].steady_db == 3.0
    assert again.watch.checkin_rule.other_db_of[link] == 8.0
    assert again._settle_db(link) == 4.0 and again._settle_db(again.links[0]) == 1.0

    for v in doc["links"].values():                  # a baseline.json from before the quiet level was kept
        del v["quiet_db"]
    (tmp_path / "baseline.json").write_text(json.dumps(doc))
    old = Brain(sessions_dir=tmp_path, settings=brain.settings)
    assert old.base == brain.base and old.quiet_db == {} and old._settle_db(link) == 1.0


def test_by_default_each_link_is_judged_against_its_own_quiet_level_and_never_under_the_contract_number(tmp_path):
    brain = Brain(sessions_dir=tmp_path)                 # the defaults: 1.5, 4 and 2 x the quiet level (#734)
    brain.on_cmd(cmd("baseline"))
    Feed(brain).play("empty_room", seed=1)
    doc = json.loads((tmp_path / "baseline.json").read_text())
    assert all(set(v) == {"base_dbm", "expected_hz", "quiet_db"} for v in doc["links"].values())
    noisy = {k: 3.0 for k in brain.links}                # a Bluetooth link that wobbles 3 dB with nobody there
    brain._set_baseline(brain.base, brain.expected_hz, noisy)
    assert all(lk.steady_db == 4.5 for lk in brain.health.links.values())
    assert all(v == 12.0 for v in brain.watch.checkin_rule.other_db_of.values())
    assert all(brain._settle_db(k) == 6.0 for k in brain.links)
    calm = {k: 0.2 for k in brain.links}                 # a quiet Wi-Fi link keeps the contract's numbers
    brain._set_baseline(brain.base, brain.expected_hz, calm)
    assert all(lk.steady_db == 0.8 for lk in brain.health.links.values())
    assert all(brain._settle_db(k) == 1.0 for k in brain.links)


def test_with_the_factors_at_0_every_rule_keeps_the_contract_number_and_the_file_its_contract_keys(tmp_path):
    off = S.DEFAULT.with_(steady_x_quiet=0.0, checkin_x_quiet=0.0, settle_x_quiet=0.0)
    brain = Brain(sessions_dir=tmp_path, settings=off)
    brain.on_cmd(cmd("baseline"))
    Feed(brain).play("empty_room", seed=1)
    doc = json.loads((tmp_path / "baseline.json").read_text())
    assert all(set(v) == {"base_dbm", "expected_hz"} for v in doc["links"].values())
    brain.quiet_db = {k: 3.0 for k in brain.links}
    brain._set_baseline(brain.base, brain.expected_hz, brain.quiet_db)
    assert all(lk.steady_db == 0.8 for lk in brain.health.links.values())
    assert all(v == 0 for v in brain.watch.checkin_rule.other_db_of.values())
    assert all(brain._settle_db(k) == 1.0 for k in brain.links)


@pytest.mark.parametrize("value", [-1, 21, True, "2"])
def test_a_factor_must_be_a_number_from_0_to_20(value):
    with pytest.raises(ValueError, match="steady_x_quiet"):
        S.DEFAULT.with_(steady_x_quiet=value)


def test_replay_takes_a_factor_with_a_decimal_point():
    from brain.replay import parse_set
    assert parse_set(["steady_x_quiet=1.5", "moving_run=8"]) == {"steady_x_quiet": 1.5, "moving_run": 8}
