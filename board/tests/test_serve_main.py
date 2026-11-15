"""board/serve.py as the unit runs it: the page is marked as the board's, and main() mounts the
store's endpoints (/history, /report) next to /ask."""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from board import serve

REPO = Path(__file__).resolve().parents[2]
STATE = {"v": 2, "type": "state", "seq": 1, "src": "live", "cam": "off", "router": "S-home", "links": [],
         "health": {"status": "ok", "blind": [], "reason": None},
         "pred": {"present": True, "kind": "person", "zone": 1, "zone_set": [1], "probs": [0, 1],
                  "motion": "still", "still_s": 1.0, "why": []},
         "alert": {"state": "none", "zone": None, "still_s": 0, "limit_s": None}}


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


@pytest.fixture
def dist(tmp_path):
    d = tmp_path / "dist"
    d.mkdir()
    (d / "index.html").write_text("<!doctype html><html><head><title>Echo</title></head><body></body></html>")
    return d


def test_the_page_the_board_serves_says_it_is_the_board(dist, tmp_path):
    server = serve.make_server("127.0.0.1", 0, dist=dist, nodes=tmp_path / "n.json", proof=tmp_path / "p.json")
    threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        for path in ("/", "/index.html", "/?src=ws"):
            status, body = get(base + path)
            assert status == 200
            assert body.startswith(b'<!doctype html><html><head><meta name="radio-sight-board" content="live">')
            assert body.count(b"radio-sight-board") == 1
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def unit(dist, tmp_path):
    """python board/serve.py, the way radio-sight-serve starts it, on a free port."""
    from store import Store
    db = tmp_path / "store.db"
    now = int(time.time() * 1000)
    store = Store(db)
    for i in range(3):
        store.add({**STATE, "t": now - 3000 + i * 1000})
    proc = subprocess.Popen([sys.executable, str(REPO / "board" / "serve.py"), "--host", "127.0.0.1", "--port", "0",
                             "--dist", str(dist), "--store", str(db), "--llm", "http://127.0.0.1:9"],
                            stderr=subprocess.PIPE, text=True, cwd=tmp_path,
                            env={**os.environ, "PYTHONPATH": ""})
    try:
        line = ""
        while "serve: http://" not in line:
            line = proc.stderr.readline()
            assert line, "serve.py exited"
        yield line.split("serve: ")[1].split(" from ")[0], now
    finally:
        proc.terminate()
        proc.wait(10)


def test_main_mounts_history_with_the_rows_the_store_saved(unit):
    base, now = unit
    status, body = get(f"{base}/history?from_t={now - 60_000}&to_t={now}")
    assert status == 200, body
    rows = json.loads(body)["rows"]
    assert len(rows) == 3 and rows[0]["present"] is True


def test_a_bad_request_to_a_mounted_endpoint_is_a_400_not_a_500(unit):
    base, now = unit
    status, body = get(f"{base}/history?from_t={now}&to_t={now - 1}")
    assert status == 400 and json.loads(body) == {"error": "to_t is before from_t"}


def test_main_mounts_report(unit):
    base, _ = unit
    status, body = get(f"{base}/report")
    assert status == 404 and "armed" in json.loads(body)["error"]   # never armed: the handler's own answer
