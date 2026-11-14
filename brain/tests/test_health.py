import json
from pathlib import Path

import numpy as np

from brain import health
from sim import fake

HZ = 10
LINKS = list(health.LINKS)
BASE = {link: -50.0 for link in LINKS}


def make(**kw):
    return health.Health(LINKS, {k: HZ for k in LINKS}, BASE, **kw)


def run(hm, t0, t1, level=lambda t, link: 0.0, alive=lambda t, link: True,
        kind=lambda t: "none", seed=0):
    """Readings at HZ per link and one update per reading tick. Returns {t: out}."""
    rng = np.random.default_rng(seed)
    outs = {}
    for i in range(round(t0 * HZ), round(t1 * HZ)):
        t = i / HZ
        for link in LINKS:
            if alive(t, link):
                hm.add(link, t * 1000, round(BASE[link] + level(t, link) + rng.normal(0, 0.7)))
        outs[round(t, 1)] = hm.update(t * 1000, kind(t))
    return outs


def kinds(outs):
    return [(t, e["kind"]) for t, o in sorted(outs.items()) for e in o["events"]]


def status(out, link):
    return next(r["status"] for r in out["links"] if r["id"] == link)


def test_all_links_ok():
    outs = run(make(), 0, 10)
    out = outs[9.9]
    assert out["health"] == {"status": "ok", "blind": [], "reason": None}
    assert {r["status"] for r in out["links"]} == {"ok"}
    row = out["links"][0]
    assert set(row) == {"id", "dbm", "base_dbm", "drop_db", "rate_hz", "expected_hz", "status"}
    assert row["rate_hz"] == HZ and abs(row["drop_db"]) <= 1.0
    assert kinds(outs) == []


def test_no_stale_before_the_first_full_window():
    outs = run(make(), 0, 1.5)
    assert all(o["health"]["status"] == "ok" for o in outs.values())


def test_dropped_link_goes_stale_then_blind_then_clears():
    lost = "east>unoq:ble"

    def alive(t, link):
        return link != lost or not (5.0 <= t < 12.0)

    outs = run(make(), 0, 20, alive=alive)
    # last reading at 4.9; the 2 s rate falls under 4 Hz (7 readings) at 6.2
    assert status(outs[6.1], lost) == "ok" and status(outs[6.2], lost) == "stale"
    assert outs[6.2]["health"] == {"status": "degraded", "blind": [], "reason": "rate"}
    # blind after 3 s stale
    assert outs[9.1]["health"]["status"] == "degraded"
    assert outs[9.2]["health"] == {"status": "blind", "blind": [lost], "reason": "rate"}
    assert status(outs[9.2], lost) == "blind"
    # back at 12.0, rate ok again at 12.7, then 3 s ok
    assert outs[15.6]["health"]["status"] == "blind"
    assert outs[15.7]["health"] == {"status": "ok", "blind": [], "reason": None}
    assert kinds(outs) == [(9.2, "blind_on"), (15.7, "blind_off")]
    on = outs[9.2]["events"][0]["info"]
    assert on == {"link": lost, "links": [lost], "reason": "rate"}
    assert outs[15.7]["events"][0]["info"]["link"] == lost


def test_jump_off_base_with_nobody_there_is_blind():
    moved = "pi5>unoq:wifi"

    def level(t, link):
        return -9.0 if link == moved and t >= 5.0 else 0.0

    outs = run(make(), 0, 12, level=level)
    first_blind = min(t for t, o in outs.items() if o["health"]["status"] == "blind")
    assert 8.0 <= first_blind <= 9.0          # median moves at about 5.5, then 3 s
    assert outs[11.9]["health"] == {"status": "blind", "blind": [moved], "reason": "jump"}
    assert kinds(outs) == [(first_blind, "blind_on")]


def test_jump_with_a_person_there_is_not_blind():
    def level(t, link):
        return -9.0 if link == "pi5>unoq:wifi" and t >= 5.0 else 0.0

    outs = run(make(), 0, 12, level=level, kind=lambda t: "person")
    assert all(o["health"]["status"] == "ok" for o in outs.values())
    outs = run(make(), 0, 12, level=level, kind=lambda t: None)   # no prediction yet
    assert all(o["health"]["status"] == "ok" for o in outs.values())


def test_short_jump_does_not_go_blind():
    def level(t, link):
        return -9.0 if link == "west>pi5:ble" and 5.0 <= t < 7.0 else 0.0

    outs = run(make(), 0, 12, level=level)
    assert all(o["health"]["status"] == "ok" for o in outs.values())


def test_blind_link_outside_the_classifier_only_degrades():
    lost = "west>pi5:ble"
    hm = make(classifier_links=[k for k in LINKS if k != lost])
    outs = run(hm, 0, 12, alive=lambda t, link: link != lost or t < 3.0)
    assert outs[11.9]["health"] == {"status": "degraded", "blind": [lost], "reason": "rate"}
    assert hm.blind is False and kinds(outs) == []


def test_dropped_link_in_the_sim_feed():
    """empty_room from sim at 15 Hz; east>pi5:ble goes quiet from 10 s."""
    lost = "east>pi5:ble"
    base = {fake.link_id(*lk): fake.baseline(*lk) for lk in fake.LINKS}
    hm = health.Health(list(base), {k: 15.0 for k in base}, base)
    next_tick, outs = 0.0, {}
    for e in fake.simulate(fake.load_path("empty_room"), rate=15.0):
        if e["type"] != "rssi":
            continue
        while e["t"] >= next_tick:
            outs[round(next_tick, 1)] = hm.update(next_tick * 1000, "none")
            next_tick += 0.1
        if not (e["link"] == lost and e["t"] >= 10.0):
            hm.add(e["link"], e["t"] * 1000, e["dbm"])
    assert all(outs[t]["health"]["status"] == "ok" for t in outs if t < 10.0)
    first_blind = min(t for t, o in outs.items() if o["health"]["status"] == "blind")
    assert 13.0 <= first_blind <= 14.5
    assert outs[max(outs)]["health"] == {"status": "blind", "blind": [lost], "reason": "rate"}
    assert [k for _, k in kinds(outs)] == ["blind_on"]


def test_builds_from_radio_nodes_json():
    doc = json.loads((Path(__file__).parents[2] / "radio" / "nodes.json").read_text())
    for link in doc["links"]:
        link["expected_hz"] = 12.0
    hm = health.Health.from_nodes(doc, base_dbm=BASE)
    assert list(hm.links) == LINKS
    assert {lk.expected_hz for lk in hm.links.values()} == {12.0}
    hm.set_expected({"pi5>unoq:wifi": 20})
    assert hm.links["pi5>unoq:wifi"].expected_hz == 20.0
