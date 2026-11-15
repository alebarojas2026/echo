"""Ask the room and the incident report on one spot and three devices (the gate layout: narrator/tests/gate_nodes.json).

The store is filled by hand here, so nothing depends on the fake feed."""
import re
from pathlib import Path

import pytest

from agent import ask as A
from agent import report as R
from agent.tools import place
from store import Store

T0 = 1_763_149_500_000
GATE = Path(__file__).resolve().parents[2] / "narrator" / "tests" / "gate_nodes.json"
ZONES, LINKS = A.layout(GATE)
SIDES = re.compile(r"\b(left|right|east|west|zone)\b", re.I)


def second(store, s, present=True, armed=False, health="ok", tamper=()):
    pred = None if present is None else (
        {"present": True, "kind": "person", "zone": 1, "zone_set": [1], "motion": "still", "still_s": 1.0}
        if present else {"present": False, "kind": "none", "zone": 0, "zone_set": [], "motion": None})
    store.add({"type": "state", "t": T0 + s * 1000, "src": "sim", "pred": pred, "links": [], "armed": armed,
               "health": {"status": health, "blind": []}, "alert": {"state": "none"}, "tamper": list(tamper)})


def event(store, s, kind, **info):
    store.add({"type": "event", "t": T0 + s * 1000, "kind": kind, "id": f"{kind}{s}", "src": "sim", "info": info})


@pytest.fixture
def store():
    """Armed at 10 s; someone is at the desk from 20 to 39 s (an intrusion at 23 s); Pi B goes quiet at 45 s."""
    s = Store(":memory:")
    for i in range(60):
        second(s, i, present=20 <= i < 40, armed=i >= 10, tamper=["pi5b"] if i >= 45 else ())
    event(s, 10, "armed")
    event(s, 23, "intrusion", zone=1)
    event(s, 30, "alert_on", zone=1)
    event(s, 45, "tamper", node="pi5b")
    return s


def model(tool, zone=0):
    return lambda messages, schema: {"tool": tool, "minutes": 10, "zone": zone, "link": "any"}


def test_the_layout_has_one_zone_and_six_links_and_the_model_is_offered_just_those():
    assert ZONES == {1: "At the desk"} and len(LINKS) == 6
    schema = A.schema(ZONES, LINKS)["properties"]
    assert schema["zone"]["enum"] == [0, 1] and schema["link"]["enum"] == ["any"] + LINKS
    assert "zone: 0 for anywhere, or 1 for At the desk." in A.messages("was anyone here?", ZONES, LINKS)[0]["content"]


def test_a_zone_name_is_said_as_a_place():
    assert place("At the desk", True) == "at the desk" and place("At the desk", False) == "at the desk"
    assert place("Gate", True) == "here"            # the only zone, with a name that is no place
    assert place("Left", False) is None and place("Bathroom", False) is None   # other layouts keep their own words


@pytest.mark.parametrize("zone", [0, 1])
def test_presence_reads_naturally_with_or_without_the_zone(store, zone):
    out = A.ask("was anyone here?", store, model("presence", zone), now_ms=T0 + 60_000, zones=ZONES, links=LINKS)
    here = "at the desk" if zone else "here"
    assert out["answer"] == (f"Yes. Someone was {here} for 20 s of the last 10 minutes, "
                             "most recently at the desk from " + out["rows"][-1]["from"] + " to " + out["rows"][-1]["to"] + ".")
    assert out["args"] == {"minutes": 10, "zone": zone or None, "link": None}
    assert out["rows"][-1]["name"] == "At the desk" and not SIDES.search(out["answer"])


@pytest.mark.parametrize("tool", ["presence", "still_spans", "alerts", "intrusions"])
def test_no_answer_names_a_side_or_says_in_at(store, tool):
    out = A.ask("a question", store, model(tool), now_ms=T0 + 60_000, zones=ZONES, links=LINKS)
    assert out["tool"] == tool and "at the desk" in out["answer"]
    assert not SIDES.search(out["answer"]) and "in At" not in out["answer"]


def test_keywords_pick_a_tool_without_any_side_words():
    assert A.by_rules("was anyone here in the last 5 minutes?") == {"tool": "presence", "minutes": 5, "zone": 0, "link": "any"}
    out = A.ask("did anyone come in after hours?", Store(":memory:"), None, now_ms=T0, zones=ZONES, links=LINKS)
    assert out["tool"] == "intrusions" and out["picked_by"] == "rules"


def test_the_report_says_at_the_desk_and_names_pi_b(store):
    out = R.report(store, now_ms=T0 + 60_000, zones=ZONES)
    assert out["intrusions"] == [{"t": T0 + 23_000, "zone": 1}] and out["tamper"] == [{"t": T0 + 45_000, "node": "pi5b"}]
    names = R.device_names(GATE)
    text = R.template(out, ZONES, names)
    assert "Intrusion alerts: 1, the first at the desk at " in text
    assert "Pi B went quiet first" in text and "Someone was here for 20 s." in text
    assert not SIDES.search(text)
