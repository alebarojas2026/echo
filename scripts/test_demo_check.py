import asyncio
from pathlib import Path
import socket
import sys
from threading import Thread

from websockets.asyncio.server import serve

from board.serve import make_server


CHECKER = Path(__file__).with_name("demo_check.py")


async def run_checker(http_port, ws_port):
    process = await asyncio.create_subprocess_exec(
        sys.executable, str(CHECKER),
        "--http", f"http://127.0.0.1:{http_port}",
        "--ws", f"ws://127.0.0.1:{ws_port}/ws",
        stdout=asyncio.subprocess.PIPE,
    )
    stdout, _ = await asyncio.wait_for(process.communicate(), timeout=15)
    return process.returncode, stdout.decode().splitlines()


def test_reachable_board(tmp_path):
    (tmp_path / "index.html").write_text("<html><body>Echo</body></html>", encoding="utf-8")
    nodes = tmp_path / "nodes.json"
    nodes.write_bytes((CHECKER.parent.parent / "radio" / "nodes.json").read_bytes())

    async def state(socket):
        await socket.send('{"v":2,"type":"state"}')

    async def silent(socket):
        await socket.wait_closed()

    async def check_servers(port):
        async with serve(state, "127.0.0.1", 0) as ws:
            code, lines = await run_checker(port, ws.sockets[0].getsockname()[1])
            assert lines[:4] == ["PASS web", "PASS nodes.json", "PASS proof.json", "PASS WebSocket"]
            # A bare state and a web server with no records: every later check says what is missing.
            assert code == 1 and [line.split(":", 1)[0] for line in lines[4:-1]] == [
                "FAIL health", "FAIL links", "FAIL model", "FAIL board clock", "FAIL records", "FAIL ask"]
            assert lines[-1] == "4 of 10 pass"
        async with serve(silent, "127.0.0.1", 0) as ws:
            code, lines = await run_checker(port, ws.sockets[0].getsockname()[1])
            assert code == 1
            assert lines[3] == "FAIL WebSocket: TimeoutError"
            assert lines[4] == "FAIL health: no state to read (see WebSocket)"

    with make_server("127.0.0.1", 0, dist=tmp_path, nodes=nodes, proof=tmp_path / "proof.json") as board:
        thread = Thread(target=board.serve_forever)
        thread.start()
        try:
            asyncio.run(check_servers(board.server_port))
        finally:
            board.shutdown()
            thread.join()


def test_unreachable_board():
    with socket.socket() as unavailable:
        unavailable.bind(("127.0.0.1", 0))
        port = unavailable.getsockname()[1]
        code, lines = asyncio.run(run_checker(port, port))
    assert code == 1
    assert [line.split(":", 1)[0] for line in lines[:4]] == [
        "FAIL web", "FAIL nodes.json", "FAIL proof.json", "FAIL WebSocket",
    ]
    assert lines[-1] == "0 of 10 pass"


def test_layout_counts_reject_a_different_layout():
    import pytest
    from scripts.demo_check import layout_counts
    with pytest.raises(ValueError, match="count differs"):
        layout_counts(b'{"nodes":[],"links":[]}')


# ---- the checks a judging day needs: sensing, trained, on time, keeping records, answering

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from scripts import demo_check

LAYOUT = demo_check.configured_layout()


def good_state(**changes):
    state = {"v": 2, "type": "state", "t": int(time.time() * 1000),
             "health": {"status": "ok", "blind": [], "reason": None},
             "links": [{"id": link["id"], "rate_hz": 9.0, "status": "ok"} for link in LAYOUT["links"]],
             "model": {"trained": True}}
    return {**state, **changes}


def test_health_names_the_links_that_are_not_ok():
    demo_check.health_check(good_state())
    blind = good_state(health={"status": "blind", "blind": ["east>unoq:ble"], "reason": "rate"})
    with pytest.raises(ValueError, match="health is blind .east>unoq:ble."):
        demo_check.health_check(blind)
    first = LAYOUT["links"][0]["id"]
    stale = good_state(health={"status": "degraded", "blind": [], "reason": None})
    stale["links"][0]["status"] = "stale"
    with pytest.raises(demo_check.Warn) as error:      # degraded is a warning: the board still predicts
        demo_check.health_check(stale)
    assert f"health is degraded ({first})" in str(error.value)
    with pytest.raises(ValueError, match="no state to read"):
        demo_check.health_check(None)


def test_every_configured_link_must_be_reporting():
    demo_check.links_check(good_state())
    state = good_state()
    quiet, gone = state["links"][0], state["links"].pop()
    quiet["rate_hz"] = 0
    with pytest.raises(ValueError) as error:
        demo_check.links_check(state)
    assert quiet["id"] in str(error.value) and gone["id"] in str(error.value)


def test_untrained_model_fails_or_warns_before_the_lesson():
    no_line = {"links": []}
    demo_check.model_check(good_state(), layout=no_line)
    untrained = good_state(model={"trained": False})
    with pytest.raises(ValueError, match="not trained"):
        demo_check.model_check(untrained, layout=no_line)
    with pytest.raises(demo_check.Warn):
        demo_check.model_check(untrained, before_lesson=True, layout=no_line)


def test_a_presence_line_needs_no_trained_model():
    line = {"links": [], "presence": {"line": "pi5>pi5b:wifi"}}
    deciding = good_state(model={"trained": False}, pred={"present": False, "kind": "none"})
    demo_check.model_check(deciding, layout=line)
    with pytest.raises(ValueError, match="take the baseline"):
        demo_check.model_check(good_state(model={"trained": False}, pred=None), layout=line)


def test_board_clock_within_a_minute_of_this_machine():
    demo_check.clock_check({"t": 1_000_000}, now_ms=1_000_000 + 59_000)
    with pytest.raises(ValueError, match="520 s behind"):
        demo_check.clock_check({"t": 1_000_000}, now_ms=1_000_000 + 520_000)
    with pytest.raises(ValueError, match="90 s ahead"):
        demo_check.clock_check({"t": 1_000_000 + 90_000}, now_ms=1_000_000)


class FakeBoard(BaseHTTPRequestHandler):
    """The web server's record and question endpoints, answering whatever the test set."""

    def log_message(self, *args):
        pass

    def _send(self, answer):
        code, body = answer if isinstance(answer, tuple) else (200, answer)
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self.server.asked.append(self.path)
        self._send(self.server.history)

    def do_POST(self):
        self.server.asked.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self._send(self.server.ask)


@pytest.fixture
def board():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeBoard)
    server.asked = []
    thread = Thread(target=server.serve_forever)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_records_are_asked_for_in_the_boards_own_time(board):
    server, base = board
    server.history = {"rows": [{"t": n} for n in range(58)]}
    demo_check.records_check(base, {"t": 5_000_000})   # nothing like this machine's clock
    assert server.asked == ["/history?from_t=4940000&to_t=5000000"]
    server.history = {"rows": [{"t": 1}] * 3}
    with pytest.raises(ValueError, match="3 records in the last minute"):
        demo_check.records_check(base, {"t": 5_000_000})
    server.history = (404, {"error": "not found"})
    with pytest.raises(ValueError, match="/history is not served"):
        demo_check.records_check(base, {"t": 5_000_000})


def test_ask_needs_an_answer_from_a_tool_picked_by_the_keywords_or_the_model(board):
    server, base = board
    server.ask = {"answer": "Nobody is here.", "tool": "presence", "picked_by": "llm"}
    demo_check.ask_check(base)
    assert server.asked == [{"question": demo_check.QUESTION}]
    server.ask = {"answer": "Nobody is here.", "tool": "presence", "picked_by": "rules"}
    demo_check.ask_check(base)
    server.ask = {"answer": "I can answer: ...", "tool": None, "picked_by": "rules"}
    with pytest.raises(demo_check.Warn, match="no tool was picked"):
        demo_check.ask_check(base)
    server.ask = {"answer": " "}
    with pytest.raises(ValueError, match="no answer"):
        demo_check.ask_check(base)
    server.ask = (503, {"error": "ask is not set up on this server"})
    with pytest.raises(ValueError, match="not set up"):
        demo_check.ask_check(base)
