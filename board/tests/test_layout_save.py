"""POST and GET /layout on board/serve.py (#510): align mode's saves on the board."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from board import layout, serve

NODES = {
    "nodes": [{"id": "unoq", "xyz_m": [1.1, 0.6, 1.0], "roles": ["receiver"]}],
    "links": [],
    "hall": {"note": "kept as it is", "beacons": [
        {"node": "h", "id": "H", "data_hex": "FFFF525348", "xyz_m": None},
        {"node": "j", "id": "J", "data_hex": "FFFF52534A", "xyz_m": None}]},
}
ROOM = {"offset_m": [1.5, -2.0], "yaw_deg": 12.5, "scale": 1.0, "cut_m": 1.4}


@pytest.fixture
def site(tmp_path):
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "index.html").write_text("<!doctype html>")
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


def call(url, body=None, content_type="application/json", raw=None):
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    req = urllib.request.Request(url + "/layout", data=data, method="GET" if data is None else "POST")
    if data is not None:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def nodes_json(url):
    with urllib.request.urlopen(url + "/nodes.json", timeout=5) as r:
        return json.loads(r.read())


def test_nothing_saved_yet(url):
    assert call(url) == (200, {"room": None, "hall_beacons": [{"node": "h", "xyz_m": None},
                                                               {"node": "j", "xyz_m": None}]})


def test_a_good_save_is_returned_and_drawn(url, site):
    before = site["nodes"].read_bytes()
    status, view = call(url, {"room": ROOM, "hall_beacons": [{"node": "h", "xyz_m": [3.8, 14.1, 2.0]}]})
    assert status == 200
    assert view == {"room": ROOM, "hall_beacons": [{"node": "h", "xyz_m": [3.8, 14.1, 2.0]},
                                                   {"node": "j", "xyz_m": None}]}
    assert call(url) == (200, view)
    served = nodes_json(url)
    assert served["hall"]["beacons"][0]["xyz_m"] == [3.8, 14.1, 2.0]
    assert {k: v for k, v in served.items() if k != "hall"} == {k: v for k, v in NODES.items() if k != "hall"}
    assert served["hall"]["note"] == "kept as it is"
    assert site["nodes"].read_bytes() == before          # radio/nodes.json itself is never written


def test_saves_add_up(url):
    call(url, {"hall_beacons": [{"node": "h", "xyz_m": [1, 2, 1]}]})
    call(url, {"room": ROOM})
    _, view = call(url, {"hall_beacons": [{"node": "j", "xyz_m": [5, 6, 1]}]})
    assert view["room"] == ROOM and [b["xyz_m"] for b in view["hall_beacons"]] == [[1, 2, 1], [5, 6, 1]]
    _, view = call(url, {"hall_beacons": [{"node": "h", "xyz_m": None}]})   # unplace one
    assert view["hall_beacons"][0]["xyz_m"] is None


@pytest.mark.parametrize("body, says", [
    ({"hall_beacons": [{"node": "east", "xyz_m": [1, 2, 1]}]}, "not a hall beacon"),
    ({"hall_beacons": [{"node": "b", "xyz_m": [1, 2, 1]}]}, "not a hall beacon"),
    ({"hall_beacons": [{"node": "h", "xyz_m": [1, 2]}]}, "xyz_m must be"),
    ({"hall_beacons": [{"node": "h", "xyz_m": [1e6, 2, 1]}]}, "xyz_m must be"),
    ({"hall_beacons": [{"node": "h", "xyz_m": [1, 2, -3]}]}, "xyz_m must be"),
    ({"hall_beacons": [{"node": "h", "xyz_m": [1, "2", 1]}]}, "xyz_m must be"),
    ({"hall_beacons": [{"node": "h", "xyz_m": [1, 2, True]}]}, "xyz_m must be"),
    ({"room": {**ROOM, "scale": 40}}, "room.scale"),
    ({"room": {**ROOM, "yaw_deg": float("nan")}}, "room.yaw_deg"),
    ({"room": {"offset_m": [0, 0]}}, "exactly"),
    ({"room": {**ROOM, "zones": []}}, "exactly"),
    ({"links": []}, "nothing else"),
    ({"hall_beacons": [{"node": "h", "xyz_m": [1, 2, 1], "data_hex": "FFFF525357"}]}, "exactly {node, xyz_m}"),
    ({}, "nothing else"),
    ([], "nothing else"),
])
def test_anything_else_is_refused_and_changes_nothing(url, body, says):
    call(url, {"hall_beacons": [{"node": "j", "xyz_m": [5, 6, 1]}]})
    status, answer = call(url, body)
    assert status == 400 and says in answer["error"]
    assert call(url)[1]["hall_beacons"][1]["xyz_m"] == [5, 6, 1]


def test_not_json_and_not_sent_as_json(url):
    assert call(url, raw=b"{nope")[0] == 400
    assert call(url, {"room": ROOM}, content_type="text/plain")[0] == 415   # a form post can't do it
    assert call(url)[1]["room"] is None


def test_a_restart_keeps_the_values(site):
    server, base = start(site)
    call(base, {"room": ROOM, "hall_beacons": [{"node": "j", "xyz_m": [-4.0, 20.0, 2.5]}]})
    server.shutdown()
    server.server_close()
    assert json.loads(site["layout_path"].read_text())["hall"] == {"j": [-4.0, 20.0, 2.5]}
    server, base = start(site)
    try:
        _, view = call(base)
        assert view["room"] == ROOM and view["hall_beacons"][1]["xyz_m"] == [-4.0, 20.0, 2.5]
        assert nodes_json(base)["hall"]["beacons"][1]["xyz_m"] == [-4.0, 20.0, 2.5]
    finally:
        server.shutdown()
        server.server_close()


def test_a_beacon_gone_from_nodes_json_is_not_drawn(site):
    store = layout.Store(site["layout_path"])
    store.save({"hall": {"h": [1, 2, 1], "x": [9, 9, 9]}})
    assert [b["node"] for b in layout.overlay(NODES, store.load())["hall"]["beacons"]] == ["h", "j"]
    assert layout.overlay({"nodes": []}, store.load()) == {"nodes": []}   # no hall section: nothing added


def test_no_save_from_outside_the_boards_networks(monkeypatch, url):
    monkeypatch.setattr(serve, "SAVE_FROM", [serve.ipaddress.ip_network("10.42.0.0/24")])
    status, answer = call(url, {"room": ROOM})
    assert status == 403 and "board's own networks" in answer["error"]
    assert call(url)[1]["room"] is None                 # GET still answers


def test_save_networks_are_the_contracts():
    assert [str(n) for n in serve.SAVE_FROM] == ["127.0.0.0/8", "192.168.77.0/24", "10.42.0.0/24"]


def test_a_broken_store_file_reads_as_nothing_saved(site):
    site["layout_path"].parent.mkdir(parents=True)
    site["layout_path"].write_text("{")
    assert layout.Store(site["layout_path"]).load() == {"room": None, "hall": {}}
