import copy

import numpy as np
import pytest

from advisor.advise import advise

# Same layout as radio/nodes.json (CONTRACTS.md section 3).
NODES = {
    "nodes": [
        {"id": "unoq", "side": "N", "xyz_m": [1.0, 2.0, 1.0], "roles": ["receiver"]},
        {"id": "pi5", "side": "S", "xyz_m": [1.0, 0.0, 1.0], "roles": ["router", "beacon", "receiver"]},
        {"id": "east", "side": "E", "xyz_m": [2.0, 1.0, 1.0], "roles": ["beacon"]},
        {"id": "west", "side": "W", "xyz_m": [0.0, 1.0, 1.0], "roles": ["beacon"]},
    ],
    "router_spots": [
        {"id": "S-home", "xyz_m": [1.0, 0.0, 1.0]},
        {"id": "S-W30", "xyz_m": [0.7, 0.0, 1.0]},
        {"id": "S-E30", "xyz_m": [1.3, 0.0, 1.0]},
    ],
    "tray_spots": [{"id": "T1", "xyz_m": [1.0, 0.2, 1.0]}],
}
T1 = (1.0, 0.2)
KEYS = ["id", "cause", "near", "xy_m", "link", "to_spot", "move_m", "dist_change_m",
        "text", "before_dbm", "after_dbm", "why"]


def xray(blobs=(), w=10, h=10, cell=0.24, origin=(-0.2, -0.2), width_m=0.15):
    """A section 5 xray with Gaussian static_db blobs [(x, y, peak_db), ...]."""
    xs = origin[0] + (np.arange(w) + 0.5) * cell
    ys = origin[1] + (np.arange(h) + 0.5) * cell
    gx, gy = np.meshgrid(xs, ys)
    static = np.zeros_like(gx)
    for x, y, peak in blobs:
        static += peak * np.exp(-((gx - x) ** 2 + (gy - y) ** 2) / (2 * width_m ** 2))
    return {"w": w, "h": h, "cell_m": cell, "origin_m": list(origin),
            "moving_db": [0.0] * (w * h), "static_db": static.ravel().tolist(), "n_links": 6}


def obj(x, y, since=14.0, near="pi5", drop=9.8):
    return {"xy_m": [x, y], "near": near, "since_s": since, "drop_db": drop}


def links(**drops):
    ids = ["pi5>unoq:wifi", "pi5>unoq:ble", "east>unoq:ble", "west>unoq:ble", "east>pi5:ble", "west>pi5:ble"]
    drops = {"pi5_unoq_wifi": 7.0, **drops}   # the Wi-Fi link is dropping unless a test says otherwise
    return [{"id": i, "drop_db": drops.get(i.replace(">", "_").replace(":", "_"), 0.0)} for i in ids]


# --- fires on an obstruction at T1 ---------------------------------------

def test_blob_at_tray_spot_gives_full_advice():
    a = advise(xray([(*T1, 9.0)]), links(pi5_unoq_wifi=7.0, east_pi5_ble=5.0), NODES, [obj(*T1)])
    assert a is not None
    assert list(a) == KEYS
    assert a["cause"] == "obstruction"
    assert a["near"] == "pi5"
    assert a["xy_m"] == [1.0, 0.2]
    assert a["link"] == "pi5>unoq:wifi"
    assert a["to_spot"] in ("S-W30", "S-E30")
    assert a["before_dbm"] is None and a["after_dbm"] is None
    assert a["why"][0] == "pi5>unoq:wifi"
    assert "east>pi5:ble" in a["why"]


def test_symmetric_blob_breaks_the_tie_the_same_way_every_time():
    # A blob straight on the line scores both spots the same; the first listed wins.
    a = advise(xray([(*T1, 9.0)]), links(), NODES, [obj(*T1)])
    b = advise(xray([(*T1, 9.0)]), links(), NODES, [obj(*T1)])
    assert a == b
    assert a["to_spot"] == "S-W30"


def test_move_and_distance_change_for_s_w30():
    a = advise(xray([(*T1, 9.0)]), links(), NODES, [obj(*T1)])
    assert a["to_spot"] == "S-W30"
    assert a["move_m"] == [-0.3, 0.0]
    # (0.7, 0) to (1, 2) is 2.022 m, the old link is 2.0 m
    assert a["dist_change_m"] == 0.02
    assert a["text"] == ("An obstruction next to the router is blocking its link to the receiver. "
                         "Move the router 30 cm west.")


# --- stays quiet ---------------------------------------------------------

def test_blob_far_from_the_link_gives_no_advice():
    assert advise(xray([(0.2, 1.7, 9.0)]), links(west_unoq_ble=6.0), NODES, [obj(0.2, 1.7, near="west")]) is None


@pytest.mark.parametrize("x, fires", [
    (1.36, True),    # peak cell centre 0.36 m from the line x = 1
    (1.60, False),   # peak cell centre 0.60 m from it
])
def test_half_a_metre_from_the_wifi_line(x, fires):
    a = advise(xray([(x, 0.64, 9.0)]), links(), NODES, [obj(x, 0.64, near="east")])
    assert (a is not None) == fires


def test_object_younger_than_five_seconds_gives_no_advice():
    assert advise(xray([(*T1, 9.0)]), links(), NODES, [obj(*T1, since=4.9)]) is None
    assert advise(xray([(*T1, 9.0)]), links(), NODES, [obj(*T1, since=5.0)]) is not None


def test_nothing_to_advise_on():
    assert advise(None, links(), NODES, [obj(*T1)]) is None
    assert advise(xray([(*T1, 9.0)]), links(), NODES, []) is None
    assert advise(xray([(*T1, 9.0)]), links(), NODES, None) is None
    # an object with no static change under it
    assert advise(xray(), links(), NODES, [obj(*T1)]) is None
    empty = xray()
    empty["static_db"] = None
    assert advise(empty, links(), NODES, [obj(*T1)]) is None
    empty["static_db"] = []
    assert advise(empty, links(), NODES, [obj(*T1)]) is None


def test_no_spot_other_than_home():
    only_home = dict(NODES, router_spots=[{"id": "S-home", "xyz_m": [1.0, 0.0, 1.0]}])
    assert advise(xray([(*T1, 9.0)]), links(), only_home, [obj(*T1)]) is None


def test_wrong_grid_size_is_an_error():
    bad = xray([(*T1, 9.0)])
    bad["w"] = 9
    with pytest.raises(ValueError):
        advise(bad, links(), NODES, [obj(*T1)])


# --- east vs west --------------------------------------------------------

@pytest.mark.parametrize("x, spot, word, other", [
    (0.85, "S-E30", "east", "west"),   # blob west of the line: S-W30's link runs right through it
    (1.15, "S-W30", "west", "east"),   # blob east of the line
])
def test_blob_off_centre_picks_the_other_side(x, spot, word, other):
    a = advise(xray([(x, 0.3, 9.0)]), links(), NODES, [obj(x, 0.3)])
    assert a["to_spot"] == spot
    assert a["move_m"] == ([0.3, 0.0] if word == "east" else [-0.3, 0.0])
    assert f"30 cm {word}" in a["text"]
    assert other not in a["text"]


def test_spot_order_does_not_decide_a_clear_winner():
    flipped = dict(NODES, router_spots=list(reversed(NODES["router_spots"])))
    assert advise(xray([(0.85, 0.3, 9.0)]), links(), flipped, [obj(0.85, 0.3)])["to_spot"] == "S-E30"
    assert advise(xray([(1.15, 0.3, 9.0)]), links(), flipped, [obj(1.15, 0.3)])["to_spot"] == "S-W30"


def test_strongest_object_near_the_link_is_the_one_used():
    # the 15 dB one is far from the line, so the 12 dB one wins over the 6 dB one
    grid = xray([(0.2, 1.7, 15.0), (1.15, 0.3, 6.0), (0.85, 1.4, 12.0)])
    objects = [obj(0.2, 1.7, near="west"), obj(1.15, 0.3), obj(0.85, 1.4, near=None)]
    a = advise(grid, links(), NODES, objects)
    assert a["xy_m"] == [0.85, 1.4]
    assert a["near"] is None


# --- the text follows the result -----------------------------------------

def test_text_changes_with_the_result():
    west = advise(xray([(1.15, 0.3, 9.0)]), links(), NODES, [obj(1.15, 0.3)])
    east = advise(xray([(0.85, 0.3, 9.0)]), links(), NODES, [obj(0.85, 0.3)])
    assert west["text"] != east["text"]
    assert west["text"].endswith("Move the router 30 cm west.")
    assert east["text"].endswith("Move the router 30 cm east.")


def test_text_uses_the_spot_distance():
    spots = copy.deepcopy(NODES)
    spots["router_spots"] = [{"id": "S-home", "xyz_m": [1.0, 0.0, 1.0]}, {"id": "S-W50", "xyz_m": [0.5, 0.0, 1.0]}]
    a = advise(xray([(*T1, 9.0)]), links(), spots, [obj(*T1)])
    assert a["to_spot"] == "S-W50"
    assert a["move_m"] == [-0.5, 0.0]
    assert "Move the router 50 cm west." in a["text"]


def test_text_names_what_the_obstruction_is_next_to():
    a = advise(xray([(1.0, 1.75, 9.0)]), links(), NODES, [obj(1.0, 1.75, near="unoq")])
    assert a["near"] == "unoq"
    assert a["text"].startswith("An obstruction next to the receiver is blocking the router's link to it.")
    # no "near" given: worked out from the nodes, and nothing is within half a metre of mid-room
    c = advise(xray([(1.0, 0.3, 9.0)]), links(), NODES, [obj(1.0, 0.3, near=None)])
    assert c["near"] == "pi5"
    b = advise(xray([(1.0, 1.0, 9.0)]), links(), NODES, [obj(1.0, 1.0, near=None)])
    assert b["near"] is None
    assert b["text"].startswith("An obstruction between the router and the receiver is blocking their link.")


def test_text_never_says_north():
    # a spot further into the room is described against the receiver, not a compass word
    spots = copy.deepcopy(NODES)
    spots["router_spots"] = [{"id": "S-home", "xyz_m": [1.0, 0.0, 1.0]}, {"id": "S-in", "xyz_m": [0.8, 0.1, 1.0]}]
    a = advise(xray([(*T1, 9.0)]), links(), spots, [obj(*T1)])
    assert a["text"].endswith("Move the router 20 cm west and 10 cm toward the receiver.")
    for x in (0.85, 1.0, 1.15):
        b = advise(xray([(x, 0.3, 9.0)]), links(), NODES, [obj(x, 0.3)])
        assert "north" not in b["text"].lower()
    assert "north" not in a["text"].lower()


# --- why links -----------------------------------------------------------

def test_why_lists_links_that_dropped_near_the_obstruction():
    drops = links(pi5_unoq_wifi=7.0, pi5_unoq_ble=4.0, east_pi5_ble=6.0, west_pi5_ble=2.0, east_unoq_ble=8.0)
    a = advise(xray([(*T1, 9.0)]), drops, NODES, [obj(*T1)])
    # wifi first, then by drop; west>pi5 dropped too little, east>unoq runs far from T1
    assert a["why"] == ["pi5>unoq:wifi", "east>pi5:ble", "pi5>unoq:ble"]


def test_inputs_are_not_changed():
    grid, ls, objects = xray([(*T1, 9.0)]), links(east_pi5_ble=5.0), [obj(*T1)]
    before = copy.deepcopy((grid, ls, NODES, objects))
    advise(grid, ls, NODES, objects)
    assert (grid, ls, NODES, objects) == before


# --- only while the Wi-Fi link is dropping now (#236) ---------------------

@pytest.mark.parametrize("drop, fires", [(7.0, True), (3.0, True), (2.9, False), (0.0, False), (-1.0, False)])
def test_no_advice_unless_the_wifi_link_drops_3_db_now(drop, fires):
    a = advise(xray([(*T1, 9.0)]), links(pi5_unoq_wifi=drop), NODES, [obj(*T1)])
    assert (a is not None) == fires


def test_no_advice_without_a_wifi_reading():
    no_drop = [dict(lk, drop_db=None) if lk["id"] == "pi5>unoq:wifi" else lk for lk in links()]
    no_row = [lk for lk in links() if lk["id"] != "pi5>unoq:wifi"]
    for ls in (no_drop, no_row, [], None):
        assert advise(xray([(*T1, 9.0)]), ls, NODES, [obj(*T1)]) is None
