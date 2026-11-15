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
    n.set_zones(n.load_zones(GATE))
    n.set_devices(n.load_devices(GATE))
    yield
    n.set_zones(zones)
    n.set_devices(devices)


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
    assert n.template("alert_on", {"zone": 1}) == "No movement at the desk for 10 seconds; time to check in."
    assert n.template("alert_off", {"zone": 1}) == "The alert at the desk is cleared."
    assert n.template("intrusion", {"zone": 1}) == "Someone is here while armed, at the desk."
    assert n.template("checkin", {"zone": 1}) == "Check-in received at the desk."
    assert n.template("object_on", {"zone": 0}) == "Something is in the Wi-Fi line, weakening the signal."
    assert n.template("recalibrating", {}) == "Recalibrating: please keep the space in front of the desk clear for 20 seconds."


def test_tamper_names_the_device_that_went_quiet():
    assert n.template("tamper", {"node": "pi5b"}) == "Pi B went quiet while the space was armed."
    assert n.template("tamper_cleared", {"node": "pi5b"}) == "Pi B is back."
    assert n.template("tamper", {"node": "pi5"}) == "Pi A went quiet while the space was armed."
    assert n.template("blind_on", {"link": "pi5b>unoq:ble"}) == "Sensor blind on the Pi B to Board Bluetooth link; predictions pause."


def test_a_zone_name_that_is_not_a_place_reads_as_here():
    n.set_zones({1: ("Gate", 10)})
    assert n.template("enter", {"zone": 1}) == "Someone is here."
    assert n.template("alert_on", {"zone": 1}) == "No movement here for 10 seconds; time to check in."


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
                     "0:02 a wave check-in was received", "0:03 the space was armed",
                     "0:04 someone came in while armed, at the desk"]
    text = r.template(events)
    assert text == ("Someone stepped up to the desk. A no-movement alert fired at the desk and a wave check-in "
                    "answered it. While it was armed, someone came in.")
    assert not SIDES.search(text) and r.problem(text, lines, camera_off=True) is None


MOVE = re.compile(r"\b(mov\w*|tip for placing)\b[^.]*\brouter\b|\bafter the move\b", re.I)


def test_the_wifi_line_across_the_gap_is_named_as_wifi_and_the_router_is_never_moved():
    """The Wi-Fi line Pi A to Pi B is the main sensor (#789): it is named with its radio, and a dead zone is
    something left standing in it, cured by clearing it. No sentence tells anyone to move the router."""
    assert n.template("blind_on", {"link": "pi5>pi5b:wifi"}) == "Sensor blind on the Pi A to Pi B Wi-Fi link; predictions pause."
    assert n.template("drift", {"link": "pi5>pi5b:ble"}) == "The Pi A to Pi B Bluetooth link is drifting from its baseline."
    assert n.template("object_off", {"node": "pi5b"}) == "The Wi-Fi line is clear again."
    assert n.template("advice_result", {"before_dbm": -71.2, "after_dbm": -63.4}) == (
        "Once it was cleared, the Wi-Fi went from -71 to -63 dBm.")
    for kind, text in every_sentence():
        assert not MOVE.search(text), (kind, text)


def test_the_recap_says_the_wifi_line_was_cleared_not_that_the_router_moved():
    events = [{"kind": k, "t": 1000 * i, "info": info} for i, (k, info) in enumerate([
        ("object_on", {"node": "pi5b"}), ("advice", {"link": "pi5>pi5b:wifi"}), ("object_off", {}),
        ("advice_result", {"before_dbm": -71.2, "after_dbm": -63.4})])]
    assert r.facts(events) == ["0:00 something was left in the Wi-Fi line", "0:01 the board found something in the Wi-Fi line",
                               "0:02 the Wi-Fi line was cleared", "0:03 once it was cleared the Wi-Fi went from -71 to -63 dBm"]
    assert r.template(events) == "Clearing the Wi-Fi line took it from -71 to -63 dBm."
    assert r.template(events[:1]) == "Something was left in the Wi-Fi line."
    assert not any(MOVE.search(line) for line in r.facts(events))
