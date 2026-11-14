import math

import pytest

from brain import features as F
from sim import fake

# sim nodes -> contract nodes (same positions: S, E, N, W midpoints).
SIM_NODE = {"n0": "pi5", "n1": "east", "n2": "unoq", "n3": "west"}
# sim zones (0 SW, 1 SE, 2 NW, 3 NE) -> contract zones (1 NW, 2 NE, 3 SW, 4 SE).
SIM_ZONE = {0: 3, 1: 4, 2: 1, 3: 2}


def sim_to_v2(name, seed=0):
    """Run a sim path and turn its events into v2 bus messages with recv_t."""
    t0 = 1_763_149_500_000
    seq = 0
    out = []
    for ev in fake.simulate(fake.load_path(name), seed=seed):
        t = t0 + round(ev["t"] * 1000)
        seq += 1
        if ev["kind"] == "rssi":
            a, b = (SIM_NODE[n] for n in ev["link"].split("-"))
            pair = {a, b}
            if pair == {"east", "west"}:
                continue  # not a contract link
            rx = "unoq" if "unoq" in pair else "pi5"
            tx = (pair - {rx}).pop()
            kinds = ["wifi", "ble"] if tx == "pi5" else ["ble"]
            for kind in kinds:
                out.append({"v": 2, "type": "rssi", "t": t, "seq": seq, "src": "sim",
                            "link": f"{tx}>{rx}:{kind}", "kind": kind, "tx": tx, "rx": rx,
                            "dbm": ev["rssi"], "recv_t": t})
        else:
            present = ev["present"]
            out.append({"v": 2, "type": "label", "t": t, "seq": seq, "src": "sim",
                        "mode": "person", "persons_in_frame": int(present),
                        "present": present,
                        "zone": SIM_ZONE[ev["zone"]] if present else None,
                        "motion": "moving" if ev["moving"] else "still",
                        "conf": 0.9, "clipped": False, "recv_t": t})
    return out


def rssi(t, link, dbm):
    return {"type": "rssi", "recv_t": t, "link": link, "dbm": dbm}


def label(t, zone, motion="still", clipped=False, mode="person"):
    return {"type": "label", "recv_t": t, "present": zone != 0, "zone": zone or None,
            "motion": motion, "clipped": clipped, "mode": mode}


def test_baseline_is_per_link_median():
    msgs = [rssi(0, "a", -50), rssi(1, "a", -52), rssi(2, "a", -90), rssi(3, "b", -60)]
    assert F.baseline(msgs) == {"a": -52, "b": -60}


def test_link_stats():
    s = F.link_stats([-60.0, -62.0, -64.0], base_dbm=-58.0)
    assert s["n"] == 3 and s["mean"] == -62.0
    assert s["min"] == -64.0 and s["max"] == -60.0
    assert s["std"] == pytest.approx(math.sqrt(8 / 3))
    assert s["drop_db"] == pytest.approx(4.0)


def test_link_stats_empty_and_no_base():
    assert F.link_stats([], -50)["n"] == 0
    assert F.link_stats([-60.0], None)["drop_db"] is None


def test_windows_are_1s_long_with_100ms_hop():
    msgs = [rssi(t, "pi5>unoq:wifi", -60) for t in range(0, 3000, 50)]
    ws = list(F.windows(msgs, {"pi5>unoq:wifi": -60}))
    assert all(w["end"] - w["start"] == 1000 for w in ws)
    assert [w["end"] for w in ws[:3]] == [1000, 1100, 1200]
    assert all(b["end"] - a["end"] == 100 for a, b in zip(ws, ws[1:]))
    # 20 readings per second -> 20 in every full window
    assert all(w["links"]["pi5>unoq:wifi"]["n"] == 20 for w in ws)


def test_window_edges_start_inclusive_end_exclusive():
    w = F.Windower({})
    w.push(rssi(0, "east>pi5:ble", -50))
    w.push(rssi(999, "east>pi5:ble", -70))
    closed = w.push(rssi(1000, "east>pi5:ble", -90))
    assert len(closed) == 1
    s = closed[0]["links"]["east>pi5:ble"]
    assert s["n"] == 2 and s["min"] == -70


def test_windows_use_recv_t_not_producer_t():
    msgs = [dict(rssi(t, "east>pi5:ble", -50), t=10**12 - t) for t in range(0, 2000, 100)]
    ends = [w["end"] for w in F.windows(msgs, {})]
    assert ends[0] == 1000


def test_messages_without_recv_t_and_other_types_are_ignored():
    w = F.Windower({})
    assert w.push({"type": "rssi", "link": "x", "dbm": -50}) == []
    assert w.push({"type": "cam", "recv_t": 5000, "state": "on"}) == []
    assert w._next_end is None


def test_missing_link_is_none_but_vector_stays_full():
    msgs = [rssi(t, "pi5>unoq:wifi", -62) for t in range(0, 2000, 100)]
    base = {"pi5>unoq:wifi": -60, "east>pi5:ble": -55}
    w = next(F.windows(msgs, base))
    assert w["links"]["east>pi5:ble"]["n"] == 0
    v = F.vector(w)
    assert len(v) == len(F.feature_names()) == len(F.LINKS) * 5
    assert v[:5] == pytest.approx([-62, 0, -62, -62, 2])
    i = F.LINKS.index("east>pi5:ble") * 5
    assert v[i:i + 5] == [-55, 0.0, -55, -55, 0.0]


def test_window_label_majority_and_drops():
    assert F.window_label([]) is None
    assert F.window_label([label(0, 2), label(1, 2, clipped=True)]) is None
    lb = F.window_label([label(0, 2), label(1, 2), label(2, 3, "moving")])
    assert lb["zone"] == 2 and lb["present"] and lb["motion"] == "still"
    empty = F.window_label([label(0, 0), label(1, 0), label(2, 4)])
    assert empty["zone"] == 0 and not empty["present"] and empty["motion"] is None


def test_label_window_drops_on_clip():
    msgs = [rssi(t, "pi5>unoq:wifi", -60) for t in range(0, 3000, 100)]
    msgs += [label(t, 1) for t in range(0, 3000, 200)]
    msgs.append(label(1500, None, clipped=True))
    ws = list(F.windows(msgs, {}))
    dropped = [w for w in ws if w["label"] is None]
    assert dropped and all(w["start"] <= 1500 < w["end"] for w in dropped)


def test_sim_empty_room_has_no_drop():
    msgs = sim_to_v2("empty_room")
    base = F.baseline(msgs)
    assert set(base) == set(F.LINKS)
    ws = list(F.windows(msgs, base))
    assert len(ws) > 200
    assert all(abs(s["drop_db"]) < 1.5 for w in ws for s in w["links"].values())
    assert all(w["label"]["zone"] == 0 for w in ws)


def test_sim_zone_tour_drops_links_and_labels_zones():
    base = F.baseline(sim_to_v2("empty_room"))
    ws = list(F.windows(sim_to_v2("zone_tour", seed=1), base))
    zones = {w["label"]["zone"] for w in ws if w["label"]}
    assert {1, 2, 3, 4} <= zones
    # Somebody in the square makes at least one link drop clearly.
    occupied = [w for w in ws if w["label"] and w["label"]["present"]]
    biggest = [max(s["drop_db"] for s in w["links"].values()) for w in occupied]
    assert sum(d > 2.0 for d in biggest) > len(occupied) // 2


def test_sim_metal_object_gives_steady_drop():
    base = F.baseline(sim_to_v2("empty_room"))
    ws = list(F.windows(sim_to_v2("metal_object"), base))
    # The object sits next to sim n1 = east: east links drop, steadily.
    east = [w["links"]["east>pi5:ble"]["drop_db"] for w in ws]
    assert min(east) > 2.0
    assert all(w["links"]["west>unoq:ble"]["drop_db"] < 1.5 for w in ws)
