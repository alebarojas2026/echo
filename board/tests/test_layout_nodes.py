"""Placed positions of the core devices (#721): POST and GET /layout, /nodes.json with them applied,
and data/nodes.local.json, the copy the brain reads."""
import copy
import json
import threading
import urllib.error
import urllib.request

import pytest

from board import layout, serve

NODES = {
    "frame": {"size_m": [1.6, 1.1], "strip_m": [1.6, 0.6], "zone_split_x_m": 0.8},
    "nodes": [{"id": "unoq", "xyz_m": [1.1, 0.6, 1.0], "roles": ["receiver"]},
              {"id": "pi5", "xyz_m": [0.8, 1.1, 1.0], "roles": ["router", "beacon", "receiver"]},
              {"id": "pi5b", "xyz_m": [0.5, 0.6, 1.0], "roles": ["beacon", "receiver"]},
              {"id": "west", "xyz_m": [0.0, 0.25, 1.0], "roles": ["beacon"]}],
    "links": [{"id": "pi5>unoq:wifi", "tx": "pi5", "rx": "unoq"}, {"id": "west>pi5b:ble", "tx": "west", "rx": "pi5b"}],
    "zone_rule": "zone = 1 + (x >= 0.8)",
    "zones": [{"id": 1, "centre_m": [0.4, 0.3]}, {"id": 2, "centre_m": [1.2, 0.3]}],
    "router_spots": [{"id": "S-home", "xyz_m": [0.8, 1.1, 1.0]}, {"id": "S-W30", "xyz_m": [0.5, 1.1, 1.0]}],
    "tray_spots": [{"id": "T1", "xyz_m": [0.86, 1.0, 1.0]}],
    "hall": {"beacons": [{"node": "h", "xyz_m": None}]},
}
PLACED = [{"id": "pi5b", "xyz_m": [0.8, -0.38, 0.85]}, {"id": "west", "xyz_m": [0.1, -0.38, 0.85]}]


@pytest.fixture
def site(tmp_path):
    (tmp_path / "dist").mkdir()
    nodes = tmp_path / "nodes.json"
    nodes.write_text(json.dumps(NODES, indent=2))
    return {"dist": tmp_path / "dist", "nodes": nodes, "proof": tmp_path / "proof.json",
            "layout_path": tmp_path / "data" / "layout.local.json"}


def start(site):
    server = serve.make_server("127.0.0.1", 0, **site)
    threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


@pytest.fixture
def url(site):
    server, base = start(site)
    yield base
    server.shutdown()
    server.server_close()


def call(url, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url + "/layout", data=data, method="GET" if data is None else "POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def nodes_json(url):
    with urllib.request.urlopen(url + "/nodes.json", timeout=5) as r:
        return json.loads(r.read())


def xyz(doc, node):
    return next(n["xyz_m"] for n in doc["nodes"] if n["id"] == node)


def test_nothing_placed_yet(url):
    assert call(url)[1]["nodes"] == []
    assert nodes_json(url) == NODES


def test_placed_positions_are_returned_and_drawn_and_nothing_else_changes(url):
    status, view = call(url, {"nodes": PLACED})
    assert status == 200 and view["nodes"] == PLACED
    served = nodes_json(url)
    assert xyz(served, "pi5b") == [0.8, -0.38, 0.85] and xyz(served, "west") == [0.1, -0.38, 0.85]
    assert xyz(served, "unoq") == [1.1, 0.6, 1.0]
    for key in ("frame", "links", "zone_rule", "zones", "router_spots", "tray_spots", "hall"):
        assert served[key] == NODES[key], key
    assert [(n["id"], n["roles"]) for n in served["nodes"]] == [(n["id"], n["roles"]) for n in NODES["nodes"]]


def test_the_router_takes_its_spots_with_it(url):
    call(url, {"nodes": [{"id": "pi5", "xyz_m": [0.8, -0.4, 1.0]}]})
    served = nodes_json(url)
    assert xyz(served, "pi5") == [0.8, -0.4, 1.0]
    assert [s["xyz_m"] for s in served["router_spots"]] == [[0.8, -0.4, 1.0], [0.5, -0.4, 1.0]]
    assert served["tray_spots"] == NODES["tray_spots"]


def test_a_post_without_nodes_keeps_them_and_an_empty_list_clears_them(url):
    call(url, {"nodes": PLACED})
    room = {"offset_m": [1.0, 2.0], "yaw_deg": 3.0, "scale": 1.0, "cut_m": 1.0}
    assert call(url, {"room": room})[1]["nodes"] == PLACED
    assert call(url, {"nodes": [PLACED[0]]})[1]["nodes"] == [PLACED[0]]   # a list is the whole placement
    assert call(url, {"nodes": []})[1]["nodes"] == []
    assert nodes_json(url) == NODES


@pytest.mark.parametrize("nodes, says", [
    ([{"id": "pi9", "xyz_m": [0, 0, 1]}], "not a node"),
    ([{"id": "h", "xyz_m": [0, 0, 1]}], "not a node"),          # a hall beacon goes in hall_beacons
    ([{"id": "west", "xyz_m": [5.5, 0, 1]}], "within -5..5"),
    ([{"id": "west", "xyz_m": [0, 0, 3.2]}], "within -5..5"),
    ([{"id": "west", "xyz_m": [0, 0]}], "within -5..5"),
    ([{"id": "west", "xyz_m": [0, "1", 1]}], "within -5..5"),
    ([{"id": "west", "xyz_m": [0, 0, 1], "roles": []}], "exactly {id, xyz_m}"),
    ([PLACED[1], PLACED[1]], "twice"),
    ([PLACED[1]] * 17, "at most 16"),
    ({"west": [0, 0, 1]}, "at most 16"),
])
def test_anything_else_is_refused_and_nothing_is_saved(url, nodes, says):
    call(url, {"nodes": PLACED})
    status, answer = call(url, {"nodes": nodes})
    assert status == 400 and says in answer["error"]
    assert call(url)[1]["nodes"] == PLACED


def test_links_or_zones_cannot_be_sent(url):
    for body in ({"nodes": PLACED, "links": []}, {"zones": []}, {"zone_rule": "x"}):
        assert call(url, body)[0] == 400
    assert nodes_json(url) == NODES


def test_a_restart_keeps_the_placement(site):
    server, base = start(site)
    call(base, {"nodes": PLACED})
    server.shutdown()
    server.server_close()
    server, base = start(site)
    try:
        assert call(base)[1]["nodes"] == PLACED and xyz(nodes_json(base), "west") == [0.1, -0.38, 0.85]
    finally:
        server.shutdown()
        server.server_close()


def test_every_save_writes_the_brains_copy(url, site):
    merged = site["layout_path"].with_name("nodes.local.json")
    call(url, {"nodes": PLACED})
    assert json.loads(merged.read_text()) == nodes_json(url)
    call(url, {"nodes": []})
    assert json.loads(merged.read_text()) == NODES


def test_write_nodes_before_the_brain_starts(tmp_path, site):
    out = tmp_path / "out" / "nodes.local.json"
    assert layout.write_nodes(site["nodes"], site["layout_path"], out) is False   # nothing saved: the file
    assert json.loads(out.read_text()) == NODES
    layout.Store(site["layout_path"]).save({"nodes": layout.clean_nodes(PLACED, layout.node_ids(NODES))})
    assert layout.main(["write-nodes", "--nodes", str(site["nodes"]), "--layout", str(site["layout_path"]),
                        "--out", str(out)]) == 0
    assert xyz(json.loads(out.read_text()), "pi5b") == [0.8, -0.38, 0.85]
    site["layout_path"].write_text("{broken")
    layout.write_nodes(site["nodes"], site["layout_path"], out)
    assert json.loads(out.read_text()) == NODES
    with pytest.raises(ValueError, match="won't write over"):
        layout.write_nodes(site["nodes"], site["layout_path"], site["nodes"])   # never radio/nodes.json itself
    assert json.loads(site["nodes"].read_text()) == NODES


def test_a_device_gone_from_nodes_json_is_not_drawn(site):
    stored = {"room": None, "hall": {}, "nodes": {"gone": [0, 0, 1], "west": [0.2, 0.2, 1.0]}}
    doc = layout.overlay(copy.deepcopy(NODES), stored)
    assert xyz(doc, "west") == [0.2, 0.2, 1.0] and [n["id"] for n in doc["nodes"]] == ["unoq", "pi5", "pi5b", "west"]
