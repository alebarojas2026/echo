"""The brain takes its layout from radio/nodes.json: links, zones, the grid and the router.

The second layout here is the desk strip proposed in the contract draft (five nodes, twelve
links, two zones). The feed for it is made up in this file; it shows the code follows the
file, and says nothing about how well a real desk works.
"""
import json
import random

from brain import features as F
from brain.core import NODES_JSON, Brain
from brain.tests.simdata import T0_MS
from brain.tests.test_core import cmd
from brain.xray import Xray, grid_shape, zone_rule

SQUARE = json.loads(NODES_JSON.read_text(encoding="utf-8"))


def desk():
    doc = json.loads(json.dumps(SQUARE))
    doc["frame"] = {"size_m": [1.6, 1.1], "strip_m": [1.6, 0.6], "zone_split_x_m": 0.8}
    doc["nodes"] = [
        {"id": "unoq", "xyz_m": [1.1, 0.6, 1.0], "roles": ["receiver"]},
        {"id": "pi5", "xyz_m": [0.8, 1.1, 1.0], "roles": ["router", "beacon", "receiver"]},
        {"id": "pi5b", "xyz_m": [0.5, 0.6, 1.0], "roles": ["beacon", "receiver"]},
        {"id": "east", "xyz_m": [1.6, 0.25, 1.0], "roles": ["beacon"]},
        {"id": "west", "xyz_m": [0.0, 0.25, 1.0], "roles": ["beacon"]}]
    ids = ["pi5>unoq:wifi", "pi5>unoq:ble", "east>unoq:ble", "west>unoq:ble", "east>pi5:ble", "west>pi5:ble",
           "pi5b>unoq:ble", "pi5>pi5b:wifi", "pi5>pi5b:ble", "east>pi5b:ble", "west>pi5b:ble", "pi5b>pi5:ble"]
    doc["links"] = [{"id": i, "tx": i.split(">")[0], "rx": i.split(">")[1].split(":")[0], "kind": i.split(":")[1],
                     "expected_hz": None} for i in ids]
    doc["zones"] = [{"id": 1, "name": "Left", "still_alert_s": 10}, {"id": 2, "name": "Right", "still_alert_s": 10}]
    doc["router_spots"] = [{"id": "S-home", "xyz_m": [0.8, 1.1, 1.0]}, {"id": "S-W30", "xyz_m": [0.5, 1.1, 1.0]},
                           {"id": "S-E30", "xyz_m": [1.1, 1.1, 1.0]}]
    return doc, ids


# which made-up links a person in each desk zone shadows, and by how much
SHADOW = {1: {"west>unoq:ble": 8, "west>pi5b:ble": 9, "west>pi5:ble": 5},
          2: {"east>unoq:ble": 8, "east>pi5b:ble": 6, "east>pi5:ble": 7}}


def desk_feed(ids, plan, t0, seed=0, silent=(), level=None):
    """plan: [(seconds, zone)] one after another. 15 readings a second per link, 7.5 labels, a cam message a second."""
    rng, t, out = random.Random(seed), t0, []
    for seconds, zone in plan:
        for i in range(int(seconds * 15)):
            for link in ids:
                if link not in silent:
                    dbm = (level or {}).get(link, -50) - SHADOW.get(zone, {}).get(link, 0) + rng.gauss(0, 1.0)
                    out.append({"v": 2, "type": "rssi", "recv_t": t, "t": t, "src": "sim", "link": link, "dbm": round(dbm)})
            if i % 2 == 0:
                out.append({"v": 2, "type": "label", "recv_t": t, "t": t, "src": "sim", "mode": "person",
                            "persons_in_frame": int(zone > 0), "present": zone > 0, "zone": zone,
                            "foot_m": None, "motion": "still" if zone else None, "conf": 0.9, "clipped": False})
            if i % 15 == 0:
                out.append({"v": 2, "type": "cam", "recv_t": t, "t": t, "src": "sim", "state": "on", "fps": 7.5})
            t += 1000 // 15
    return out, t


def taught_desk(**kw):
    doc, ids = desk()
    brain, t = Brain(nodes=doc, **kw), T0_MS

    def play(plan, seed, session=None, **more):
        nonlocal t
        msgs, t = desk_feed(ids, plan, t, seed, **more)
        if session:
            brain.on_cmd(cmd("record_start", session=session, purpose="train", walker="w"))
            brain.on_message({"v": 2, "type": "meta", "recv_t": msgs[0]["recv_t"], "session": session, "purpose": "train"})
        for m in msgs:
            brain.on_message(m)
            if m["type"] == "label":
                brain.state()                      # the live loop takes state all the time
        if session:
            brain.on_cmd(cmd("record_stop"))

    brain.on_cmd(cmd("baseline"))
    play([(25, 0)], 1)
    play([(10, 0), (10, 1), (10, 2), (5, 0), (10, 2), (10, 1)], 2, session="d1")
    brain.on_cmd(cmd("train"))
    return brain, ids, play


def test_the_square_layout_reads_the_same_from_the_file_as_from_the_old_constants():
    brain = Brain()
    assert brain.links == F.LINKS and brain.zone_ids == [1, 2, 3, 4] and brain.router_node == "pi5"
    assert brain.router_links == ["pi5>unoq:wifi", "pi5>unoq:ble", "east>pi5:ble", "west>pi5:ble"]
    assert (brain.xray.grid.w, brain.xray.grid.h, round(brain.xray.grid.cell_m, 3)) == (10, 10, 0.24)
    assert [round(v, 3) for v in brain.xray.grid.origin_m] == [-0.2, -0.2]
    assert [zone_rule(SQUARE)(x, y) for x, y in ((0.5, 1.5), (1.5, 1.5), (0.5, 0.5), (1.5, 0.5))] == [1, 2, 3, 4]


def test_the_desk_layout_gets_its_grid_zone_rule_and_router_links_from_the_file():
    doc, ids = desk()
    xray = Xray.from_nodes(doc)
    assert grid_shape(doc["frame"]) == (16, 12) and grid_shape(SQUARE["frame"]) == (10, 10)
    assert (xray.grid.w, xray.grid.h, round(xray.grid.cell_m, 4)) == (16, 12, 0.125)
    assert [round(v, 4) for v in xray.grid.origin_m] == [-0.2, -0.2] and xray.W.shape == (12, 192)
    zone = zone_rule(doc)
    assert [zone(0.4, 0.3), zone(1.2, 0.3), zone(0.8, 0.0), zone(0.86, 1.0), zone(-0.1, 0.3)] == [1, 2, 2, 0, 0]

    brain = Brain(nodes=doc)
    assert brain.links == tuple(ids) and brain.zone_ids == [1, 2]
    # pi5 as tx or rx: links 1, 2, 5, 6, 8, 9 and 12. "pi5b" has the letters pi5 in it and is another node.
    assert brain.router_links == [ids[i - 1] for i in (1, 2, 5, 6, 8, 9, 12)]
    brain.xray.set_router("S-W30")
    assert brain.xray.nodes["pi5"] == (0.5, 1.1) and brain.xray.nodes["pi5b"] == (0.5, 0.6)


def test_the_whole_loop_runs_on_twelve_links_and_two_zones():
    brain, ids, play = taught_desk()
    assert brain.model is not None and brain.model.classes == [0, 1, 2]
    assert len(brain.model.features) == 12 * len(F.STATS)
    seen = []
    for zone in (1, 2, 0, 2):
        play([(6, zone)], 10 + zone)
        state = brain.state()
        pred = state["pred"]
        seen.append(pred["zone"])
        assert len(pred["probs"]) == 3 and set(pred["zone_set"]) <= {1, 2} and set(pred["why"]) <= set(ids)
    assert seen == [1, 2, 0, 2]
    assert len(state["links"]) == 12 and state["xray"]["w"] == 16 and state["xray"]["h"] == 12
    assert len(state["xray"]["moving_db"]) == 192 and state["xray"]["n_links"] == 12
    assert state["alert"]["zone"] in (None, 1, 2)


def test_a_desk_model_file_is_not_loaded_into_the_square_layout(tmp_path):
    brain, ids, play = taught_desk(sessions_dir=tmp_path)
    assert (tmp_path / "model.pkl").exists()
    assert Brain(nodes=desk()[0], sessions_dir=tmp_path).model is not None     # the same layout: loaded
    square = Brain(sessions_dir=tmp_path)                                      # six links, four zones
    assert square.model is None


def test_links_heard_over_the_hotspot_go_quiet_without_blinding_the_sensor():
    brain, ids, play = taught_desk()
    heard_by_pi_b = [i for i in ids if i.split(">")[1].startswith("pi5b:")]
    assert len(heard_by_pi_b) == 4
    play([(8, 1)], 30, silent=heard_by_pi_b)       # the hotspot link is blocked: Pi B's readings stop
    state = brain.state()
    rows = {r["id"]: r["status"] for r in state["links"]}
    assert all(rows[i] in ("stale", "blind") for i in heard_by_pi_b)            # shown in their own rows
    assert state["health"]["status"] == "degraded" and state["pred"] is not None and state["pred"]["zone"] == 1
    play([(8, 1)], 31, silent=["east>unoq:ble"])   # a link on the cable side still blinds it
    assert brain.state()["health"]["status"] == "blind" and brain.state()["pred"] is None


def file_feed(doc, plan, t0, seed=0):
    """A made-up feed for whatever layout a nodes.json describes: a person in zone k shadows every
    link whose place in the file, modulo the number of zones, is k - 1."""
    ids, n = [link["id"] for link in doc["links"]], len(doc["zones"])
    zones = [int(z["id"]) for z in doc["zones"]]
    rng, t, out = random.Random(seed), t0, []
    for seconds, zone in plan:
        for i in range(int(seconds * 15)):
            for k, link in enumerate(ids):
                drop = 8 if zone and k % n == zones.index(zone) else 0
                out.append({"v": 2, "type": "rssi", "recv_t": t, "t": t, "src": "sim", "link": link,
                            "dbm": round(-50 - drop + rng.gauss(0, 1.0))})
            if i % 2 == 0:
                out.append({"v": 2, "type": "label", "recv_t": t, "t": t, "src": "sim", "mode": "person",
                            "persons_in_frame": int(zone > 0), "present": zone > 0, "zone": zone,
                            "foot_m": None, "motion": "still" if zone else None, "conf": 0.9, "clipped": False})
            if i % 15 == 0:
                out.append({"v": 2, "type": "cam", "recv_t": t, "t": t, "src": "sim", "state": "on", "fps": 7.5})
            t += 1000 // 15
    return out, t


def test_on_the_repos_own_nodes_json_every_state_and_event_passes_the_contract():
    """Whatever layout radio/nodes.json holds today (the square, or the desk strip once the contract
    moves), the loop runs on it and what it sends passes contracts/schemas as they are today."""
    from contracts.check import errors

    repo = NODES_JSON.parent.parent.parent / "radio" / "nodes.json"      # not this folder's pinned square
    doc = json.loads(repo.read_text(encoding="utf-8"))
    zones = [int(z["id"]) for z in doc["zones"]]
    brain, t, bad = Brain(nodes=doc), T0_MS, []

    def play(plan, seed, session=None):
        nonlocal t
        msgs, t = file_feed(doc, plan, t, seed)
        if session:
            brain.on_cmd(cmd("record_start", session=session, purpose="train", walker="w"))
            brain.on_message({"v": 2, "type": "meta", "recv_t": msgs[0]["recv_t"], "session": session, "purpose": "train"})
        for m in msgs:
            brain.on_message(m)
            if m["type"] == "label":
                state = brain.state()
                bad.extend(errors(state))
                for event in brain.pop_events():
                    bad.extend(errors(event))
        if session:
            brain.on_cmd(cmd("record_stop"))
        return state

    brain.on_cmd(cmd("baseline"))
    play([(25, 0)], 1)
    play([(8, 0)] + [(8, z) for z in zones] + [(4, 0)] + [(8, z) for z in reversed(zones)], 2, session="f1")
    brain.on_cmd(cmd("train"))
    for zone in zones:
        state = play([(5, zone)], 20 + zone)
        assert state["pred"]["zone"] == zone and len(state["pred"]["probs"]) == 1 + len(zones)
    state = play([(5, 0)], 30)
    assert state["pred"]["present"] is False
    classifier = [link for link in doc["links"] if link.get("classifier") is not False]   # the x-ray leaves the others out
    assert len(state["links"]) == len(doc["links"]) and state["xray"]["n_links"] == len(classifier)
    w, h = grid_shape(doc["frame"])
    assert (state["xray"]["w"], state["xray"]["h"]) == (w, h) and len(state["xray"]["static_db"]) == w * h
    assert not bad, bad[:5]


def test_after_router_home_only_a_link_with_the_router_at_one_end_can_ask_for_a_recalibration():
    brain, ids, play = taught_desk()
    brain.pop_events()
    brain.on_cmd(cmd("router_home"))
    play([(6, 0)], 40, level={"east>pi5b:ble": -55})      # 5 dB off base, but pi5b is not the router
    assert "recalibrating" not in [e["kind"] for e in brain.pop_events()] and brain.capture is None
    brain.on_cmd(cmd("router_home"))
    play([(6, 0)], 41, level={"pi5b>pi5:ble": -55})       # the router is its receiver: this one counts
    assert "recalibrating" in [e["kind"] for e in brain.pop_events()]
