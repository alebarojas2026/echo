"""Fast checks that the lab's link model behaves (SIMULATED data)."""
import numpy as np

from lab import rf


def test_shadow_is_deepest_on_the_line_and_gone_far_away():
    a, b = (1.0, 0.0), (1.0, 2.0)
    r = np.array([0.0, 0.1, 0.2, 0.6])
    loss = rf.shadow_db(1.0 + r, np.full(4, 1.0), a, b, rf.LAMBDA_M["wifi"], 0.4, 8.0, 1.75)
    assert abs(loss[0] - 8.0) < 1e-6
    assert loss[0] > loss[1] > loss[2]
    assert abs(loss[3]) < 0.5


def test_short_people_block_less():
    a, b = (1.0, 0.0), (1.0, 2.0)
    h = np.array([1.0, 1.75])
    loss = rf.shadow_db(np.ones(2), np.ones(2), a, b, rf.LAMBDA_M["wifi"], 0.4, 8.0, h)
    assert loss[0] < loss[1]


def test_messages_follow_the_contract_and_rates():
    rng = np.random.default_rng(0)
    sc = rf.Script(rng, rf.Env())
    sc.idle(2)
    sc.enter(rf.Person())
    sc.walk_to(1.5, 0.5)
    sc.stand(5)
    sc.leave()
    tl = rf.Timeline(sc)
    msgs = rf.messages(tl, seed=0)
    assert [m["recv_t"] for m in msgs] == sorted(m["recv_t"] for m in msgs)
    rssi = [m for m in msgs if m["type"] == "rssi"]
    assert {m["link"] for m in rssi} == set(rf.LINKS)
    assert all(isinstance(m["dbm"], int) and m["v"] == 2 and m["src"] == "sim" for m in rssi)
    wifi = sum(m["link"] == rf.WIFI for m in rssi) / tl.T
    phone = sum(m["link"] == "east>unoq:ble" for m in rssi) / tl.T
    assert 15 <= wifi <= 22 and 4 <= phone <= 10
    labels = [m for m in msgs if m["type"] == "label"]
    assert labels and all(("zone" in m and "clipped" in m) for m in labels)

