"""POST /ask on the board's web server (board/serve.py)."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from agent.ask import ask
from board import serve
from store import Store
from store.__main__ import fill_from_sim

NOW = 1_763_149_500_000


def start(tmp_path, ask_fn):
    server = serve.make_server("127.0.0.1", 0, dist=tmp_path, nodes=tmp_path / "n.json",
                               proof=tmp_path / "p.json", ask=ask_fn)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def post(url, body: bytes):
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


@pytest.fixture
def store():
    store = Store(":memory:")
    fill_from_sim(store, "demo", end_ms=NOW)
    return store


@pytest.fixture
def room(tmp_path, store):
    pick = lambda messages, schema: {"tool": "alerts", "minutes": 10, "zone": 0, "link": "any"}
    server, url = start(tmp_path, lambda q: ask(q, store, pick, now_ms=NOW))
    yield url
    server.shutdown()


def test_ask_answers_with_the_rows_and_the_time(room, store):
    alerts = len(store.events(kinds=("alert_on",)))   # the demo path stands still once, on every layout
    status, reply = post(room + "/ask", json.dumps({"question": "any alerts?"}).encode())
    assert status == 200 and reply["tool"] == "alerts" and reply["picked_by"] == "rules" and reply["src"] == "sim"
    assert alerts == 1 and reply["answer"].startswith(f"No-movement alerts in the last 10 minutes: {alerts}.")
    assert reply["rows"] and isinstance(reply["ms"], int)


@pytest.mark.parametrize("body", [b"", b"not json", b"[]", b'{"q": "x"}', b'{"question": ""}',
                                  b'{"question": 5}', json.dumps({"question": "x" * 3000}).encode()])
def test_a_bad_request_is_400(room, body):
    status, reply = post(room + "/ask", body)
    assert status == 400 and "question" in reply["error"]


def test_other_posts_are_404(room):
    assert post(room + "/nodes.json", b"{}")[0] == 404


def test_without_the_agent_ask_is_503(tmp_path):
    server, url = start(tmp_path, None)
    assert post(url + "/ask", b'{"question": "x"}')[0] == 503
    server.shutdown()


def test_a_failing_answer_is_500_and_says_nothing_about_why(tmp_path):
    def broken(question):
        raise RuntimeError("secret detail")
    server, url = start(tmp_path, broken)
    status, reply = post(url + "/ask", b'{"question": "x"}')
    assert status == 500 and "secret" not in json.dumps(reply)
    server.shutdown()


def test_the_real_wiring_reads_the_store_file(tmp_path):
    db = tmp_path / "store.db"
    fill_from_sim(Store(db), "demo")
    reply = serve.room_ask(db, "http://127.0.0.1:9")("was anyone here in the last 10 minutes?")   # no model there
    assert reply["picked_by"] == "rules" and reply["answer"].startswith("Yes. Someone was here")


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def test_ask_last_is_the_latest_story_from_memory_and_null_before_one(tmp_path, store, monkeypatch):
    from agent import ask as A
    from agent import endpoints
    monkeypatch.setattr(A, "_LAST", {"reply": None})   # as at start
    server = serve.make_server("127.0.0.1", 0, dist=tmp_path, nodes=tmp_path / "n.json", proof=tmp_path / "p.json",
                               ask=lambda q: ask(q, store, None, now_ms=NOW), routes={("GET", "/ask/last"): endpoints.ask_last})
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        assert get(url + "/ask/last") == (200, None)
        status, story = post(url + "/ask", json.dumps({"question": "what happened?"}).encode())
        assert status == 200 and story["tool"] == "story"
        post(url + "/ask", json.dumps({"question": "any alerts?"}).encode())   # not a story: the last story stays
        status, last = get(url + "/ask/last")
        assert status == 200 and last == {**story, "question": "what happened?", "asked_t": NOW}
        assert {"rows", "steps", "answer"} <= set(last) and store.events(NOW + 1) == []   # nothing written
        monkeypatch.setattr(serve, "SAVE_FROM", [serve.ipaddress.ip_network("10.42.0.0/24")])
        status, doc = get(url + "/ask/last")
        assert status == 403 and "board's own networks" in doc["error"]
    finally:
        server.shutdown()


def test_the_real_wiring_mounts_ask_last(tmp_path):
    assert ("GET", "/ask/last") in serve.agent_routes(str(tmp_path / "store.db"), "http://127.0.0.1:9")
