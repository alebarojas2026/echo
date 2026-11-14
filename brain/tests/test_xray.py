import json
from pathlib import Path

import numpy as np
import pytest

from brain import xray
from sim import fake

RATE_HZ = 10


def seg_dist(p, a, b):
    """Distance from point p to the segment a-b."""
    p, a, b = (np.asarray(v, float) for v in (p, a, b))
    ab = b - a
    f = np.clip(np.dot(p - a, ab) / np.dot(ab, ab), 0.0, 1.0)
    return float(np.linalg.norm(p - (a + f * ab)))


def body_drop(p, link, peak_db, width_m, nodes=xray.NODES):
    """Drop on a link from a body at p: peak on the line, fading with distance."""
    if p is None:
        return 0.0
    tx, rx, _ = xray.link_ends(link)
    return peak_db * np.exp(-(seg_dist(p, nodes[tx], nodes[rx]) / width_m) ** 2)


def run(xr, t0, t1, drop_at, kind_at=None, noise_db=0.5, links=xray.LINKS):
    """Readings at RATE_HZ, rounded to whole dB like real RSSI. With kind_at,
    one update per tick too. Returns {t: out}."""
    rng = np.random.default_rng(0)
    outs = {}
    for i in range(round(t0 * RATE_HZ), round(t1 * RATE_HZ)):
        t = i / RATE_HZ
        for link in links:
            xr.add(link, t * 1000, round(drop_at(t, link) + rng.normal(0, noise_db)))
        if kind_at:
            outs[round(t, 1)] = xr.update(t * 1000, kind_at(t))
    return outs


def walk(a, b, t_a, t_b):
    """Position at time t of someone walking from a (at t_a) to b (at t_b)."""
    def at(t):
        if t < t_a or t > t_b:
            return None
        f = (t - t_a) / (t_b - t_a)
        return (a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]))
    return at


def cell_at(grid, x, y):
    return int(np.argmin(np.hypot(grid.centres[:, 0] - x, grid.centres[:, 1] - y)))


def test_output_has_the_section_5_shape():
    xr = xray.Xray()
    run(xr, 0, 3, lambda t, link: 0.0, links=xray.LINKS[:5])
    out = xr.update(3000)
    assert set(out["xray"]) == {"w", "h", "cell_m", "origin_m", "moving_db", "static_db", "n_links"}
    x = out["xray"]
    assert (x["w"], x["h"], x["cell_m"], x["origin_m"]) == (10, 10, 0.24, [-0.2, -0.2])
    assert len(x["moving_db"]) == len(x["static_db"]) == 100
    assert x["n_links"] == 5  # the sixth link sent nothing
    assert out["objects"] == [] and out["events"] == []


def test_grid_size_is_configurable():
    g, wide = xray.Xray(w=20, h=20).grid, xray.Grid(w=12, h=10)
    assert (g.n, g.cell_m, g.origin_m) == (400, pytest.approx(0.12), pytest.approx((-0.2, -0.2)))
    assert (wide.cell_m, wide.origin_m) == (pytest.approx(0.24), pytest.approx((-0.44, -0.2)))


def contract_centre(xr_out, k):
    """Centre of flat cell k by the section 5 rule: index = iy * w + ix."""
    w, cell = xr_out["w"], xr_out["cell_m"]
    ix, iy = k % w, k // w
    return (xr_out["origin_m"][0] + (ix + 0.5) * cell, xr_out["origin_m"][1] + (iy + 0.5) * cell)


def test_cells_go_row_by_row_from_the_south_edge():
    xr = xray.Xray()
    out = xr.update(0)["xray"]
    for k in range(xr.grid.n):
        assert xr.grid.centres[k] == pytest.approx(contract_centre(out, k))
    assert xr.grid.centres[0] == pytest.approx((-0.08, -0.08))    # south-west
    assert xr.grid.centres[9] == pytest.approx((2.08, -0.08))     # south-east
    assert xr.grid.centres[90] == pytest.approx((-0.08, 2.08))    # north-west


def test_object_at_t1_lands_in_the_cell_the_contract_gives():
    t1 = xray.TRAY_SPOTS["T1"]
    xr = xray.Xray()
    run(xr, 0, 8, lambda t, link: body_drop(t1, link, 6.0, 0.25))
    out = xr.update(8000, "none")["xray"]
    k = int(np.argmax(out["static_db"]))
    x, y = contract_centre(out, k)
    assert np.hypot(x - t1[0], y - t1[1]) < 0.2    # (0.88 or 1.12, 0.16)
    # read with x and y swapped, the same cell would be on the west side
    assert k // out["w"] == 1 and k % out["w"] in (4, 5)


def test_builds_from_radio_nodes_json():
    doc = json.loads((Path(__file__).parents[2] / "radio" / "nodes.json").read_text())
    xr = xray.Xray.from_nodes(doc)
    assert xr.links == list(xray.LINKS)
    assert np.allclose(xr.W, xray.Xray().W)
    xr.set_router("S-E30")
    assert xr.nodes["pi5"] == (1.3, 0.0)


def test_projection_matches_the_formula():
    xr = xray.Xray()
    W, alpha = xr.W, xray.default_alpha(xr.W)
    direct = np.linalg.inv(W.T @ W + alpha * np.eye(W.shape[1])) @ W.T
    assert xr.P.shape == (100, 6)
    assert np.allclose(xr.P, direct, atol=1e-9)


def test_weights_follow_the_ellipse():
    xr = xray.Xray()
    row = xr.W[xray.LINKS.index("pi5>unoq:wifi")]
    g = xr.grid
    assert row[cell_at(g, 1.12, 0.88)] == pytest.approx(1 / np.sqrt(2.0))
    assert row[cell_at(g, 1.36, 0.88)] == 0.0   # 0.36 m off the line, outside
    assert row[cell_at(g, -0.08, -0.08)] == 0.0


@pytest.mark.parametrize("start, end, spot", [
    ((0.6, 1.0), (1.4, 1.0), (1.0, 1.0)),   # across the middle, over pi5>unoq
    ((1.3, 1.3), (1.7, 1.7), (1.5, 1.5)),   # across east>unoq
])
def test_person_crossing_shows_in_moving_db(start, end, spot):
    person = walk(start, end, 10.0, 12.0)

    def drop(t, link):
        d = body_drop(person(t), link, 8.0, 0.2)
        return d * (1 + 0.25 * np.sin(37 * t))  # a moving body flutters

    xr = xray.Xray()
    run(xr, 0, 11.5, drop)
    out = xr.update(11500, "person")
    moving = np.array(out["xray"]["moving_db"])
    assert moving.max() > 0.2
    x, y = xray.hot_spot(moving, xr.grid.centres)
    assert np.hypot(x - spot[0], y - spot[1]) < 0.3
    assert max(out["xray"]["static_db"]) < 0.1
    assert out["objects"] == []


def test_steady_drop_near_t1_is_a_static_object_near_pi5():
    t1 = xray.TRAY_SPOTS["T1"]
    placed = {"until": 1e9}

    def drop(t, link):  # on the tray from t = 1 s: centred on pi5>unoq:wifi
        on = 1.0 <= t < placed["until"]
        return body_drop(t1 if on else None, link, 6.0, 0.25)

    xr = xray.Xray()
    run(xr, 0, 4, drop)
    assert xr.update(4000, "none")["objects"] == []   # not steady for 5 s yet

    run(xr, 4, 12, drop)
    out = xr.update(12000, "object")
    static = np.array(out["xray"]["static_db"])
    assert static.max() > 0.3
    assert static.max() > 3 * max(out["xray"]["moving_db"])
    (obj,) = out["objects"]
    assert obj["near"] == "pi5" and obj["since_s"] == 0.0
    assert np.hypot(obj["xy_m"][0] - t1[0], obj["xy_m"][1] - t1[1]) < 0.25
    assert obj["drop_db"] == pytest.approx(6.0, abs=1.0)
    assert [e["kind"] for e in out["events"]] == ["object_on"]
    assert out["events"][0]["info"]["node"] == "pi5"
    assert out["events"][0]["info"]["link"].startswith("pi5>unoq")

    run(xr, 12, 15, drop)
    out = xr.update(15000, "object")
    assert [o["since_s"] for o in out["objects"]] == [3.0] and out["events"] == []

    placed["until"] = 15.0   # taken off the tray
    run(xr, 15, 22, drop)
    out = xr.update(22000, "none")
    assert out["objects"] == []
    assert [e["kind"] for e in out["events"]] == ["object_off"]


def test_metal_object_sim_path_shows_an_object_near_its_node():
    path = fake.load_path("metal_object")
    (o,) = path["objects"]
    spot = (o["x"], o["y"])

    def drop(t, link):
        return body_drop(spot, link, o.get("drop_db", 6.0), o.get("width_m", 0.25))

    xr = xray.Xray()
    run(xr, 0, path["duration_s"], drop)
    (obj,) = xr.update(path["duration_s"] * 1000, "none")["objects"]
    assert obj["near"] == xr.nearest_node(spot) == "east"
    assert np.hypot(obj["xy_m"][0] - spot[0], obj["xy_m"][1] - spot[1]) < 0.5


def test_object_mid_square_has_no_near_node():
    mid = (1.0, 1.0)   # on pi5>unoq, 1 m from every node
    xr = xray.Xray()
    run(xr, 0, 8, lambda t, link: body_drop(mid, link, 6.0, 0.25))
    out = xr.update(8000, "none")
    (obj,) = out["objects"]
    assert obj["near"] is None
    assert np.hypot(obj["xy_m"][0] - mid[0], obj["xy_m"][1] - mid[1]) < 0.3
    assert out["events"][0]["info"]["node"] is None


def test_static_needs_a_steady_raw_std_under_0_8_db():
    xr = xray.Xray()
    run(xr, 0, 8, lambda t, link: 6.0, noise_db=1.2)   # steady on average, noisy readings
    out = xr.update(8000, "none")
    assert max(out["xray"]["static_db"]) == 0.0 and out["objects"] == []


def test_person_standing_still_never_becomes_an_object():
    spot = (1.0, 1.0)   # on pi5>unoq, still from 5 s to 15 s, then gone

    def drop(t, link):
        return body_drop(spot if 5.0 <= t < 15.0 else None, link, 8.0, 0.2)

    def kind(t):
        return "person" if 5.0 <= t < 15.0 else "none"

    xr = xray.Xray()
    outs = run(xr, 0, 25, drop, kind)
    assert all(o["objects"] == [] and o["events"] == [] for o in outs.values())
    assert max(max(o["xray"]["static_db"]) for o in outs.values()) < 0.1
    assert np.allclose(xr.static_link_db, 0.0, atol=0.5)
    moving = np.array(outs[14.0]["xray"]["moving_db"])   # still there, still seen
    x, y = xray.hot_spot(moving, xr.grid.centres)
    assert moving.max() > 0.2 and np.hypot(x - spot[0], y - spot[1]) < 0.3
    assert max(outs[24.9]["xray"]["moving_db"]) < 0.1


def test_people_part_is_the_drop_above_the_static_part():
    t1, spot = xray.TRAY_SPOTS["T1"], (1.0, 1.0)

    def drop(t, link):   # an object on T1, then a person on the same link from 10 s
        d = body_drop(t1, link, 6.0, 0.25)
        return d + (body_drop(spot, link, 8.0, 0.2) if t >= 10.0 else 0.0)

    xr = xray.Xray()
    outs = run(xr, 0, 12, drop, lambda t: "person" if t >= 10.0 else "none")
    wifi = xray.LINKS.index("pi5>unoq:wifi")
    assert xr.static_link_db[wifi] == pytest.approx(6.0, abs=1.0)   # frozen, not 14
    people, _, _ = xr.link_levels(12.0, "person")
    assert people[wifi] == pytest.approx(8.0, abs=1.0)
    assert len(outs[11.9]["objects"]) == 1


def test_moving_the_router_30_cm_west_rebuilds_p():
    xr = xray.Xray()
    home_P = xr.P.copy()
    xr.set_router("S-W30")
    assert xr.nodes["pi5"] == (0.7, 0.0)
    moved = dict(xray.NODES, pi5=(0.7, 0.0))
    assert np.allclose(xr.P, xray.projection(xray.weight_matrix(moved, xray.LINKS, xr.grid)))
    assert not np.allclose(xr.P, home_P)
    row = xr.W[xray.LINKS.index("pi5>unoq:wifi")]
    x_mid = (xr.grid.centres[:, 0] * row).sum() / row.sum()
    assert x_mid == pytest.approx(0.85, abs=0.08)   # the link now leans west
    xr.set_router("S-home")
    assert np.allclose(xr.P, home_P)
