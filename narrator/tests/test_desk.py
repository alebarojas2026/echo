"""The desk layout's words: "on the left" / "on the right", Pi B, the tray at zone 0, armed mode."""
import json

import pytest

from narrator import narrate as n
from narrator import recap as r

DESK = {1: ("Left", 10), 2: ("Right", 10)}
DESK_NODES = ("unoq", "pi5", "pi5b", "east", "west")


@pytest.fixture
def desk():
    saved = dict(n.ZONES)
    n.set_zones(DESK)
    yield
    n.set_zones(saved)


def every_sentence():
    for kind in n.EVENT_KINDS:
        for zone in (None, 0, 1, 2):
            for node in (None, *DESK_NODES):
                info = {"zone": zone, "node": node, "link": "west>pi5b:ble", "before_dbm": -71.2, "after_dbm": -63.4}
                yield kind, n.template(kind, {k: v for k, v in info.items() if v is not None})


def test_every_desk_sentence_passes_the_checks(desk):
    for kind, text in every_sentence():
        assert text, kind
        assert "zone" not in text and "room" not in text.replace("radio", ""), (kind, text)
        assert n.problem(text, text, camera_off=kind not in ("cam_on", "cam_stalled")) is None, (kind, text)


def test_the_desk_says_left_and_right(desk):
    assert n.template("enter", {"zone": 1}) == "Someone just stepped up on the left."
    assert n.template("alert_on", {"zone": 2}) == "No movement on the right for 10 seconds; time to check in."
    assert n.template("object_on", {"zone": 0, "node": "pi5"}) == "A new object near the router is weakening the signal."
    assert n.template("intrusion", {"zone": 1}) == "Someone is here while armed, on the left."
    assert n.template("blind_on", {"link": "west>pi5b:ble"}) == "Sensor blind on the west beacon to second Pi link; predictions pause."
    assert "on the left or on the right" in n.system() and "zone 1" not in n.system()
    assert n.examples()[0][1] == "Someone just stepped up on the right."


def test_desk_recap(desk):
    events = [{"kind": k, "t": 1000 * i, "info": info} for i, (k, info) in enumerate([
        ("enter", {"zone": 1}), ("zone_change", {"zone": 2}), ("alert_on", {"zone": 2}), ("checkin", {"zone": 2}),
        ("armed", {}), ("intrusion", {"zone": 1}), ("object_on", {"zone": 0, "node": "pi5"})])]
    lines = r.facts(events)
    assert lines[:3] == ["0:00 someone stepped up on the left", "0:01 someone moved over, now on the right",
                         "0:02 no-movement alert on the right"]
    assert "0:05 someone came in while armed, on the left" in lines
    text = r.template(events)
    assert text.startswith("Someone stood on the left and on the right. A no-movement alert fired on the right")
    assert "zone" not in text and r.problem(text, lines, camera_off=True) is None


def test_every_node_in_nodes_json_has_words():
    ids = {node["id"] for node in json.loads(n.NODES_JSON.read_text())["nodes"]}
    assert ids | set(DESK_NODES) <= set(n.NODES)


def test_unknown_links_and_kinds_never_break_a_sentence():
    assert n.template("blind_on", {"link": "h>unoq:ble"}) == "Sensor blind on the h to receiver link; predictions pause."
    assert n.template("blind_on", {"link": "not a link"}) == "Sensor blind: a radio link is failing, so predictions pause."
    assert n.template("something_new", {}) is None
    nar = n.Narrator(lambda m: ("", None), lambda m: None, clock=lambda: 0)
    nar.observe({"type": "event", "kind": "something_new", "t": 0, "info": {}})
    assert nar.pending is None
