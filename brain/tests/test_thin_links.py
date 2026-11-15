""""classifier": false on a link in nodes.json (#641): read, shown and counted for tamper, but no
feature, never a reason for SENSOR BLIND, and never what a baseline waits for."""
from brain import features as F
from brain.core import Brain
from brain.health import Health
from brain.tests.simdata import T0_MS
from brain.tests.test_baseline_rates_measured import feed
from brain.tests.test_core import cmd
from brain.tests.test_layout import desk, desk_feed

THIN = ["pi5>pi5b:ble", "pi5b>pi5:ble"]       # the two Pi-to-Pi Bluetooth links
CABLE = "pi5b>pi5:ble"                        # ... of which this one reaches the board over the cable


def thin_desk():
    doc, ids = desk()
    for link in doc["links"]:
        if link["id"] in THIN:
            link["classifier"] = False
    return doc, ids


def taught(doc, ids, **kw):
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
                brain.state()
        if session:
            brain.on_cmd(cmd("record_stop"))

    brain.on_cmd(cmd("baseline"))
    play([(25, 0)], 1)
    play([(10, 0), (10, 1), (10, 2), (5, 0), (10, 2), (10, 1)], 2, session="d1")
    brain.on_cmd(cmd("train"))
    return brain, play


def test_a_thin_link_is_listed_and_measured_but_is_no_feature_and_no_xray_row():
    doc, ids = thin_desk()
    brain, play = taught(doc, ids)
    kept = [i for i in ids if i not in THIN]
    assert brain.links == tuple(ids) and brain.model_links == tuple(kept)        # the order of the rest is the file's
    assert brain.model.features == F.feature_names(kept) and len(brain.model.features) == 10 * len(F.STATS)
    assert brain.xray.links == kept and CABLE not in brain.router_links
    play([(6, 1)], 11)
    state = brain.state()
    rows = {r["id"]: r for r in state["links"]}
    assert len(rows) == 12 and all(rows[i]["status"] == "ok" and rows[i]["base_dbm"] is not None for i in THIN)
    assert all(rows[i]["why"] == 0.0 for i in THIN) and not set(state["pred"]["why"]) & set(THIN)
    assert state["pred"]["zone"] == 1 and state["xray"]["n_links"] == 10


def test_a_thin_link_that_dies_never_blinds_the_sensor_but_shows_it_in_its_own_row():
    doc, ids = thin_desk()
    brain, play = taught(doc, ids)
    play([(8, 1)], 30, silent=[CABLE])
    state = brain.state()
    row = next(r for r in state["links"] if r["id"] == CABLE)
    assert row["status"] in ("stale", "blind")
    assert state["health"] == {"status": "degraded", "blind": [], "reason": "rate"}
    assert state["pred"] is not None and state["pred"]["zone"] == 1
    assert not any(e["kind"] == "blind_on" for e in brain.pop_events())


def test_the_same_link_without_the_flag_does_blind_it():
    doc, ids = desk()
    brain, play = taught(doc, ids)
    play([(8, 1)], 30, silent=[CABLE])
    state = brain.state()
    assert state["health"]["status"] == "blind" and state["health"]["blind"] == [CABLE] and state["pred"] is None


def test_a_baseline_finishes_while_a_thin_link_is_silent_and_waits_for_any_other():
    doc, _ = thin_desk()
    brain = Brain(nodes=doc)
    brain.on_cmd(cmd("baseline"))
    done = feed(brain, 30, lambda link: 8.0, 1, silent=lambda link, s: link in THIN)
    assert done is not None and done <= 21.5
    assert not set(THIN) & set(brain.base) and len(brain.base) == 10             # nothing heard: no level for them
    assert all(brain.expected_hz[i] == 0 for i in THIN)
    state = brain.state()
    assert [r["id"] for r in state["links"]] == [i for i in brain.links if i not in THIN]   # never heard: not listed
    assert state["health"]["status"] == "ok"

    brain = Brain(nodes=doc)
    brain.on_cmd(cmd("baseline"))
    done = feed(brain, 45, lambda link: 8.0, 1, silent=lambda link, s: link == "east>unoq:ble" and 5 <= s < 10)
    assert done is not None and done >= 29.5                                     # a classifier link still restarts it


def test_a_thin_link_still_counts_for_tamper():
    """Pi B's cable-side links are both thin here; unplugging Pi B while armed is still noticed."""
    doc, ids = thin_desk()
    brain, play = taught(doc, ids)
    brain.on_cmd(cmd("arm", on=True))
    brain.pop_events()
    play([(8, 0)], 40, silent=[i for i in ids if "pi5b" in i.replace(":", ">").split(">")[:2]])
    kinds = [(e["kind"], e["info"].get("node")) for e in brain.pop_events()]
    assert ("tamper", "pi5b") in kinds
    assert brain.state()["tamper"] == ["pi5b"]


def test_after_router_home_a_thin_router_link_off_its_base_asks_for_no_recalibration():
    doc, ids = thin_desk()
    brain, play = taught(doc, ids)
    brain.on_cmd(cmd("router_moved", spot="S-W30"))
    play([(2, 0)], 50)
    brain.on_cmd(cmd("router_home"))
    brain.pop_events()
    play([(5, 0)], 51, level={CABLE: -58})          # 8 dB off its base, and nobody is asked about it
    assert not any(e["kind"] == "recalibrating" for e in brain.pop_events())


def test_a_link_under_4_a_second_at_the_baseline_shows_stale_but_is_never_blind_by_rate():
    def run(expected_hz):
        hm = Health(["a", "b"], {"a": expected_hz, "b": 10.0})
        seen = []
        for i in range(120):                         # 12 s: "a" stops after 2 s, "b" keeps coming
            now = 1000 + i * 100
            if i < 20:
                hm.add("a", now, -50)
            hm.add("b", now, -50)
            out = hm.update(now)
            seen.append(next(r["status"] for r in out["links"] if r["id"] == "a"))
        return seen[-1], out["health"]["status"]

    assert run(3.9) == ("stale", "degraded")
    assert run(4.0) == ("blind", "blind")
