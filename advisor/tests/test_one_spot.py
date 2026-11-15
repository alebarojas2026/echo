"""On one spot (radio/layouts/gate.json) the router is cabled beside the board: no advice ever names a spot to move it to.

The gate's dead zone is something left standing in the Wi-Fi line across the gap (Pi A to Pi B); clearing it is the cure,
so the advisor has nothing to say there, wherever the object is and whichever lines drop."""
import copy
import json
from pathlib import Path

import pytest

from advisor.advise import advise, fixed_router
from advisor.tests.test_advise import DESK, NODES, obj, xray

GATE = json.loads((Path(__file__).resolve().parents[2] / "radio" / "layouts" / "gate.json").read_text(encoding="utf-8"))
TRAY = tuple(GATE["tray_spots"][0]["xyz_m"][:2])     # on the desk, next to the 8 cm Wi-Fi line Pi A to the board
GAP = (0.4, 0.3)                                     # the spot, in the Wi-Fi line Pi A to Pi B


def gate_xray(blobs):
    """The gate's grid: frame.size_m plus 0.2 m each side, cells of 0.125 m."""
    w, h = (round((s + 0.4) / 0.125) for s in GATE["frame"]["size_m"])
    return xray(blobs, w=w, h=h, cell=0.125, width_m=0.1)


def gate_links(drop=9.0):
    """Every line on the gate dropping, the Wi-Fi ones most: the strongest case for advice."""
    return [{"id": link["id"], "drop_db": drop if link["kind"] == "wifi" else 5.0} for link in GATE["links"]]


def test_the_gate_has_one_zone_and_a_fixed_router_and_the_other_layouts_do_not():
    assert len(GATE["zones"]) == 1 and fixed_router(GATE)
    assert not fixed_router(DESK) and not fixed_router(NODES)


@pytest.mark.parametrize("where", [TRAY, GAP])
def test_no_advice_on_the_gate_wherever_the_object_is(where):
    assert advise(gate_xray([(*where, 9.0)]), gate_links(), GATE, [obj(*where, since=30.0)]) is None


def test_the_same_scene_with_two_zones_would_have_moved_the_router():
    """So the rule above is what keeps the gate quiet, not the scene: the tray on the desk line gives advice
    once the file has a second zone."""
    two = copy.deepcopy(GATE)
    two["zones"].append({"id": 2, "name": "Other", "centre_m": [0.4, 0.3], "still_alert_s": 10})
    a = advise(gate_xray([(*TRAY, 9.0)]), gate_links(), two, [obj(*TRAY, since=30.0)])
    assert a is not None and a["to_spot"] in ("S-W30", "S-E30") and "Move the router" in a["text"]
