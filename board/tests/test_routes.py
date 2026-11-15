"""Mounted JSON endpoints on board/serve.py: how GET /history, GET /report and POST /ask plug in
(CONTRACTS.md section 10). The handlers here are stand-ins; the real ones live in their lanes."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from board import serve

T0 = 1763149300000
MIN = 60_000
SAVED = [{"t": T0, "present": True, "zone": 2, "zone_set": [2], "motion": "still", "armed": True,
          "alert": False, "health": "ok", "tamper": []},
         {"t": T0 + 2000, "present": None, "zone": None, "zone_set": [], "motion": None, "armed": True,
          "alert": False, "health": "blind", "tamper": ["east"]}]


def history(req):
    from_t, to_t = serve.time_span(req.query)
    return {"from_t": from_t, "to_t": to_t, "step_s": 1, "rows": [r for r in SAVED if from_t <= r["t"] <= to_t]}


def report(req):
    from_t, to_t = serve.time_span(req.query, max_ms=None, required=False)
    return {"from_t": from_t, "to_t": to_t}


def echo(req):
    body = req.json()
    if not isinstance(body, dict) or not isinstance(body.get("question"), str):
        raise serve.ApiError(400, 'send {"question": "..."}')
    return {"answer": body["question"], "client": req.client}


def broken(req):
    raise RuntimeError("the store went away")


ROUTES = {("GET", "/history"): history, ("GET", "/report"): report, ("POST", "/ask"): echo,
          ("GET", "/broken"): broken, ("GET", "/not-a-dict"): lambda req: [1, 2]}


@pytest.fixture
def url(tmp_path):
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "index.html").write_text("<!doctype html><title>Radio Sight</title>")
    (tmp_path / "nodes.json").write_text("{}")
    server = serve.make_server("127.0.0.1", 0, dist=tmp_path / "dist", nodes=tmp_path / "nodes.json",
                               proof=tmp_path / "proof.json", layout_path=tmp_path / "layout.json",
                               routes=ROUTES)
    threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def call(url, method="GET", body=None):
    req = urllib.request.Request(url, data=body, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def answer(url, method="GET", body=None):
    status, headers, raw = call(url, method, body)
    assert headers["Content-Type"] == "application/json"
    return status, json.loads(raw)


def test_history_rows_come_back_as_the_handler_gives_them(url):
    status, doc = answer(f"{url}/history?from_t={T0}&to_t={T0 + 5000}")
    assert status == 200 and doc["rows"] == SAVED        # the missing second stays missing, null stays null
    assert doc["rows"][1]["present"] is None


def test_thirty_minutes_is_allowed_and_more_is_a_plain_400(url):
    assert answer(f"{url}/history?from_t={T0}&to_t={T0 + 30 * MIN}")[0] == 200
    status, doc = answer(f"{url}/history?from_t={T0}&to_t={T0 + 30 * MIN + 1}")
    assert status == 400 and doc["error"].startswith("at most 30 minutes per call")


@pytest.mark.parametrize("query, says", [
    ("", "give both from_t and to_t"),
    (f"?from_t={T0}", "give both from_t and to_t"),
    (f"?from_t=soon&to_t={T0}", "from_t must be a time in epoch milliseconds"),
    (f"?from_t={T0}&to_t=-5", "to_t must be a time in epoch milliseconds"),
    (f"?from_t={T0}.5&to_t={T0}", "from_t must be"),
    (f"?from_t={T0 + 1}&to_t={T0}", "to_t is before from_t"),
    (f"?from_t={T0}&from_t={T0}&to_t={T0}", "given more than once"),
])
def test_a_bad_span_is_a_400_with_a_message(url, query, says):
    status, doc = answer(f"{url}/history{query}")
    assert status == 400 and says in doc["error"]


def test_report_takes_no_span_or_a_long_one(url):
    assert answer(f"{url}/report") == (200, {"from_t": None, "to_t": None})
    assert answer(f"{url}/report?from_t={T0}&to_t={T0 + 600 * MIN}")[1]["to_t"] == T0 + 600 * MIN
    status, doc = answer(f"{url}/report?to_t={T0}")
    assert status == 400 and "or neither" in doc["error"]


def test_a_mounted_post_gets_its_body(url):
    status, doc = answer(f"{url}/ask", "POST", json.dumps({"question": "anyone here?"}).encode())
    assert status == 200 and doc == {"answer": "anyone here?", "client": "127.0.0.1"}
    status, doc = answer(f"{url}/ask", "POST", b"{nope")
    assert (status, doc) == (400, {"error": "not JSON"})
    status, doc = answer(f"{url}/ask", "POST", b"x" * (serve.MAX_API_BODY + 1))
    assert status == 413


def test_a_failing_handler_is_a_json_500_and_the_server_keeps_going(url):
    assert answer(f"{url}/broken") == (500, {"error": "the board could not answer"})
    assert answer(f"{url}/not-a-dict")[0] == 500
    assert answer(f"{url}/history?from_t={T0}&to_t={T0}")[0] == 200


def test_the_wrong_method_and_unknown_paths(url):
    assert answer(f"{url}/history", "POST", b"{}") == (405, {"error": "use GET"})
    assert answer(f"{url}/nothing-here", "POST", b"{}") == (404, {"error": "not found"})
    status, _, raw = call(f"{url}/ask")                     # GET on a POST endpoint is not the handler
    assert status == 404 and b"question" not in raw


def test_head_answers_without_a_body(url):
    status, headers, raw = call(f"{url}/history?from_t={T0}&to_t={T0}", "HEAD")
    assert status == 200 and raw == b"" and int(headers["Content-Length"]) > 0


def test_only_on_the_boards_own_networks(monkeypatch, url):
    monkeypatch.setattr(serve, "SAVE_FROM", [serve.ipaddress.ip_network("10.42.0.0/24")])
    status, doc = answer(f"{url}/history?from_t={T0}&to_t={T0}")
    assert status == 403 and "board's own networks" in doc["error"]
    assert answer(f"{url}/ask", "POST", b'{"question": "x"}')[0] == 403
    assert call(url + "/")[0] == 200                         # the screen itself is still served


def test_the_screen_and_its_files_are_unchanged(url):
    status, _, raw = call(url + "/")
    assert status == 200 and b"Radio Sight" in raw
    assert call(url + "/nodes.json")[0] == 200


def test_no_routes_by_default(tmp_path):
    server = serve.make_server("127.0.0.1", 0, dist=tmp_path, nodes=tmp_path / "n.json")
    try:
        assert server.routes == {}
    finally:
        server.server_close()


def test_time_span_on_its_own():
    assert serve.time_span({"from_t": str(T0), "to_t": str(T0 + 1000)}) == (T0, T0 + 1000)
    assert serve.time_span({}, required=False) == (None, None)
    with pytest.raises(serve.ApiError) as e:
        serve.time_span({"from_t": "0", "to_t": str(31 * MIN)})
    assert e.value.status == 400
