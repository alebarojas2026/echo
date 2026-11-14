import http.client
import json
import socket
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from board import serve

REPO = Path(__file__).resolve().parents[2]
NODES = {"nodes": [{"id": "unoq", "xyz_m": [1.0, 2.0, 1.0]}], "links": []}
PROOF = {"zone": {"correct": 47, "total": 52}, "bytes_out": 0}


@pytest.fixture
def site(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Radio Sight</title>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("outside dist")
    paths = {"dist": dist, "nodes": tmp_path / "nodes.json", "proof": tmp_path / "proof.json"}
    paths["nodes"].write_text(json.dumps(NODES))
    paths["proof"].write_text(json.dumps(PROOF))
    return paths


@pytest.fixture
def url(site):
    server = serve.make_server("127.0.0.1", 0, **site)
    thread = threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def leaves(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from leaves(v)
    else:
        yield obj


def test_serves_the_screen(url):
    status, headers, body = get(url + "/")
    assert status == 200 and b"Radio Sight" in body
    assert headers["Content-Type"].startswith("text/html")
    assert headers["Cache-Control"] == "no-cache"


def test_scripts_have_a_module_safe_type(url):
    status, headers, _ = get(url + "/assets/app.js")
    assert status == 200 and headers["Content-Type"] == "text/javascript"


def test_nodes_json(url):
    status, headers, body = get(url + "/nodes.json")
    assert status == 200 and json.loads(body) == NODES
    assert headers["Content-Type"] == "application/json"
    assert headers["Cache-Control"] == "no-cache"


def test_nodes_json_is_read_fresh(url, site):
    site["nodes"].write_text(json.dumps({"links": [{"id": "pi5>unoq:wifi", "expected_hz": 9.5}]}))
    assert json.loads(get(url + "/nodes.json")[2])["links"][0]["expected_hz"] == 9.5


def test_missing_nodes_json_is_404(url, site):
    site["nodes"].unlink()
    status, headers, body = get(url + "/nodes.json")
    assert status == 404 and "error" in json.loads(body)


def test_broken_nodes_json_is_503(url, site):
    site["nodes"].write_text("{nope")
    assert get(url + "/nodes.json")[0] == 503


def test_proof_json(url):
    status, _, body = get(url + "/proof.json?t=123")
    assert status == 200 and json.loads(body) == PROOF


@pytest.mark.parametrize("damage", ["missing", "broken"])
def test_proof_json_falls_back_to_all_null(url, site, damage):
    if damage == "missing":
        site["proof"].unlink()
    else:
        site["proof"].write_text("{nope")
    status, headers, body = get(url + "/proof.json")
    got = json.loads(body)
    assert status == 200 and headers["Content-Type"] == "application/json"
    assert set(got) == {"zone", "threshold_zone", "person_vs_object", "false_alarms_per_min",
                        "train_s", "ms_per_decision", "watts", "bytes_out", "images_stored",
                        "models_on_board", "measured_at", "commit"}
    assert set(got["watts"]) == {"idle", "teaching", "radio_only", "source"}
    assert all(v is None for v in leaves(got))


def test_head_has_no_body(url):
    host, port = url.removeprefix("http://").split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=5)
    conn.request("HEAD", "/proof.json")
    r = conn.getresponse()
    assert r.status == 200 and int(r.headers["Content-Length"]) > 0 and r.read() == b""
    conn.close()


def test_no_directory_listing(url):
    assert get(url + "/assets/")[0] == 404


def test_cannot_escape_dist(url):
    host, port = url.removeprefix("http://").split(":")
    for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt"):
        conn = http.client.HTTPConnection(host, int(port), timeout=5)
        conn.request("GET", path)
        r = conn.getresponse()
        assert r.status == 404 and b"outside dist" not in r.read()
        conn.close()


def test_unbuilt_screen_says_so(site):
    site["dist"] = site["dist"].parent / "not-built"
    server = serve.make_server("127.0.0.1", 0, **site)
    threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        status, _, body = get(base + "/")
        assert status == 503 and b"not built" in body
        assert get(base + "/proof.json")[0] == 200
    finally:
        server.shutdown()
        server.server_close()


def test_runs_as_a_script(site):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    proc = subprocess.Popen(
        [sys.executable, "board/serve.py", "--host", "127.0.0.1", "--port", str(port),
         "--dist", str(site["dist"]), "--nodes", str(site["nodes"]), "--proof", str(site["proof"])],
        cwd=REPO, stderr=subprocess.PIPE, text=True)
    try:
        assert f"127.0.0.1:{port}" in proc.stderr.readline()
        base = f"http://127.0.0.1:{port}"
        assert get(base + "/")[0] == 200
        assert json.loads(get(base + "/nodes.json")[2]) == NODES
        assert json.loads(get(base + "/proof.json")[2]) == PROOF
    finally:
        proc.terminate()
        proc.wait(5)
