"""One spot, three devices (gate_nodes.json, this folder's copy of the gate layout): sentences say
"at the desk", never a side or a zone number, and the devices are called what the file calls them."""
import json
import re
from pathlib import Path

import pytest

from narrator import narrate as n
from narrator import recap as r

GATE = Path(__file__).with_name("gate_nodes.json")
DOC = json.loads(GATE.read_text(encoding="utf-8"))
SIDES = re.compile(r"\b(the left|the right|east|west|zone|side)\b", re.I)   # "the router left" names no side


@pytest.fixture(autouse=True)
def gate():
    zones, devices = dict(n.ZONES), dict(n.DEVICES)
    crossing = set(n.CROSSING_WIFI)
    n.set_zones(n.load_zones(GATE))
    n.set_devices(n.load_devices(GATE))
    n.CROSSING_WIFI.clear()
    n.CROSSING_WIFI.update(n.load_crossing_wifi(GATE))
    yield
    n.set_zones(zones)
    n.set_devices(devices)
    n.CROSSING_WIFI.clear()
    n.CROSSING_WIFI.update(crossing)


def every_sentence():
    for kind in n.EVENT_KINDS:
        for zone in (None, 0, 1):
            for node in (None, *[node["id"] for node in DOC["nodes"]]):
                for link in [link["id"] for link in DOC["links"]]:
                    info = {"zone": zone, "node": node, "link": link, "before_dbm": -71.2, "after_dbm": -63.4}
                    yield kind, n.template(kind, {k: v for k, v in info.items() if v is not None})


def test_the_file_gives_one_zone_and_three_devices():
    assert n.ZONES == {1: ("At the desk", 10)} and n.spot() and not n.desk()
    assert [n._device(node["id"]) for node in DOC["nodes"]] == ["the Board", "Pi A", "Pi B"]


def test_no_sentence_names_a_side_a_zone_or_a_room():
    for kind, text in every_sentence():
        assert text, kind
        assert not SIDES.search(text) and "room" not in text.replace("radio", ""), (kind, text)
        assert "at at" not in text.lower() and "in at" not in text.lower(), (kind, text)
        assert n.problem(text, text, camera_off=kind not in ("cam_on", "cam_stalled")) is None, (kind, text)


def test_the_spot_says_at_the_desk():
    assert n.template("enter", {"zone": 1}) == "Someone is at the desk."
    assert n.template("exit", {"zone": 1}) == "Someone just stepped away from the desk."
    assert n.template("alert_on", {"zone": 1}) == "No movement at the desk for 10 seconds. Step aside and back to say you're okay."
    assert n.template("alert_off", {"zone": 1}) == "The alert at the desk is cleared."
    assert n.template("alert_off", {"zone": 1, "why": "left"}) == "They left while the alert was up."
    assert n.template("alert_off", {"zone": 1, "why": "moved"}) == "They moved, so the alert is cleared."
    assert n.template("alert_off", {"zone": 1, "why": "checkin"}) == "The alert at the desk is cleared."
    assert n.template("intrusion", {"zone": 1}) == "Someone is here while armed, at the desk."
    assert n.template("checkin", {"zone": 1}) == "Check-in received at the desk."
    assert n.template("object_on", {"zone": 0}) == "Something was left in the Wi-Fi line."
    assert n.template("recalibrating", {}) == "Recalibrating: please keep the space in front of the desk clear for 20 seconds."


def test_tamper_names_the_device_that_went_quiet():
    assert n.template("tamper", {"node": "pi5b"}) == "Pi B went quiet while the space was armed."
    assert n.template("tamper_cleared", {"node": "pi5b"}) == "Pi B is back."
    assert n.template("tamper", {"node": "pi5"}) == "Pi A went quiet while the space was armed."
    assert n.template("blind_on", {"link": "pi5b>unoq:ble"}) == "Sensor blind on the second Pi to receiver link; predictions pause."


def test_a_zone_name_that_is_not_a_place_reads_as_here():
    n.set_zones({1: ("Gate", 10)})
    assert n.template("enter", {"zone": 1}) == "Someone is here."
    assert n.template("alert_on", {"zone": 1}) == "No movement here for 10 seconds. Step aside and back to say you're okay."


def test_the_model_is_told_about_one_spot_and_no_sides():
    system = n.system()
    assert "one spot in front of a desk" in system and "Say at the desk" in system
    assert "left" not in system and "zone 1" not in system
    assert n.examples()[0][1] == "Someone is at the desk."
    assert n.example_zone() == 1


def test_the_recap_of_a_visit_to_the_spot():
    demo = r.sample_demo()
    assert [kind for kind, _ in demo] == ["enter", "alert_on", "checkin", "alert_off", "cam_off", "exit"]
    events = [{"kind": k, "t": 1000 * i, "info": info} for i, (k, info) in enumerate(
        demo[:3] + [("armed", {}), ("intrusion", {"zone": 1})])]
    lines = r.facts(events)
    assert lines == ["0:00 someone stepped up to the desk", "0:01 no-movement alert at the desk",
                     "0:02 a check-in was received", "0:03 the space was armed",
                     "0:04 someone came in while armed, at the desk"]
    text = r.template(events)
    assert text == ("Someone stepped up to the desk. A no-movement alert fired at the desk and a check-in "
                    "answered it. While it was armed, someone came in.")
    assert not SIDES.search(text) and r.problem(text, lines, camera_off=True) is None


@pytest.mark.parametrize("motion, words", [("still", "standing still"), ("moving", "moving")])
def test_narration_uses_existing_current_motion(motion, words):
    from contracts.check import errors
    nar = n.Narrator(lambda messages: (messages[-1]["content"].split("Facts: ")[1], "fake"), lambda msg: None,
                     clock=lambda: 10_000)
    nar.observe({"type": "state", "t": 10_000, "pred": {"present": True, "kind": "person", "motion": motion}})
    out = nar.narrate({"type": "event", "t": 10_000, "kind": "enter", "id": "enter1", "src": "sim", "info": {"zone": 1}})
    assert out["text"] == f"Someone is at the desk, {words}."
    assert errors(out) == []


def test_person_cannot_be_narrated_as_an_object():
    nar = n.Narrator(lambda messages: ("", None), lambda msg: None, clock=lambda: 10_000)
    person = {"type": "state", "t": 10_000, "pred": {"present": True, "kind": "person", "motion": "still"}}
    obj = {"type": "event", "t": 10_000, "kind": "object_on", "id": "object1", "info": {}}
    nar.observe(person)
    nar.observe(obj)
    assert nar.pending is None
    nar.state = None
    nar.observe(obj)
    nar.observe(person)
    assert nar.pending is None


def test_gain_never_assumes_the_cabled_router_was_moved():
    info = {"before_dbm": -60, "after_dbm": -50}
    assert n.template("advice_result", info) == "The Wi-Fi signal changed from -60 to -50 dBm."
    assert "router" not in n.template("advice", {})
    assert "router" not in r.template([{"kind": "advice_result", "info": info}])
    assert n.problem("Moving the router improved the Wi-Fi.", n.template("advice_result", info), False)
    assert n.problem("A dead zone appeared at the desk.", "Someone is at the desk, standing still.", False)


@pytest.mark.parametrize("link, present, allowed", [("pi5>pi5b:wifi", False, True), ("pi5>unoq:wifi", False, False),
                                                  ("pi5>pi5b:wifi", True, False)])
def test_object_narration_requires_no_person_and_the_configured_crossing_wifi(link, present, allowed):
    nar = n.Narrator(lambda messages: ("", None), lambda msg: None, clock=lambda: 10_000)
    nar.observe({"type": "state", "t": 10_000, "pred": {"kind": "object", "present": present},
                 "links": [{"id": link, "status": "ok", "drop_db": 12}]})
    nar.observe({"type": "event", "t": 10_000, "kind": "object_on", "id": "o1", "info": {}})
    assert (nar.due(10_000) is not None) is allowed


def _state(t, here):
    pred = {"present": True, "kind": "person", "zone": 1, "motion": "still"} if here else {"present": False, "kind": "none", "zone": None}
    return {"v": 2, "type": "state", "t": t, "src": "live", "pred": pred, "cam": "off"}


def _event(t, kind, id):
    return {"v": 2, "type": "event", "t": t, "seq": 1, "src": "live", "id": id, "kind": kind, "info": {"zone": 1}}


def _spot_narrator():
    clock, sent = [10_000], []
    nar = n.Narrator(lambda messages: (messages[-1]["content"].split("Facts: ")[1], "fake"), sent.append, clock=lambda: clock[0])
    return nar, sent, clock


def test_a_leaving_is_not_said_once_they_are_back_on_the_spot():
    # Seen on the kit: "Someone just stepped away from the desk." under "Someone is here, standing still".
    # The leaving waited its turn (one sentence every 8 s) and was said after they had stepped back on.
    nar, sent, clock = _spot_narrator()
    nar.observe(_state(10_000, True)); nar.observe(_event(10_000, "enter", "e1")); nar.step()
    clock[0] = 15_500
    nar.observe(_state(15_500, False)); nar.observe(_event(15_500, "exit", "e2"))
    assert nar.step() is None                                  # inside the 8 s
    clock[0] = 18_000
    nar.observe(_state(18_000, True))                          # back on the spot before the leaving was said
    assert nar.step() is None and nar.pending is None          # so it is never said
    assert [m["event_id"] for m in sent] == ["e1"]


def test_an_arrival_is_not_said_once_they_have_gone_again():
    nar, sent, clock = _spot_narrator()
    nar.observe(_state(10_000, True)); nar.observe(_event(10_000, "enter", "e1"))
    clock[0] = 10_400
    nar.observe(_state(10_400, False))                         # gone before the sentence's turn
    assert nar.step() is None and nar.pending is None and sent == []


def test_a_line_that_now_says_the_opposite_is_put_right_at_the_next_turn_however_old_the_event():
    nar, sent, clock = _spot_narrator()
    nar.observe(_state(10_000, True)); nar.observe(_event(10_000, "enter", "e1")); nar.step()
    clock[0] = 18_000
    nar.observe(_state(18_000, False)); nar.observe(_event(18_000, "exit", "e2")); nar.step()
    assert [m["event_kind"] for m in sent] == ["enter", "exit"]
    clock[0] = 19_000
    nar.observe(_state(19_000, True)); nar.observe(_event(19_000, "enter", "e3"))    # the line now says "stepped away"
    clock[0] = 25_900
    nar.observe(_state(25_900, True))
    assert nar.step() is None                                  # still inside the 8 s after the last sentence
    clock[0] = 26_000
    nar.observe(_state(26_000, True))
    msg = nar.step()                                           # 7 s old, and said: the screen must not go on saying they left
    assert msg["event_id"] == "e3" and "desk" in msg["text"] and "away" not in msg["text"]
    clock[0] = 40_000
    nar.observe(_state(40_000, True)); nar.observe(_event(36_000, "zone_change", "e4"))
    assert nar.step() is None                                  # nothing to put right: an old event is dropped as before
