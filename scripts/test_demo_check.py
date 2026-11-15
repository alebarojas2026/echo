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
    (tmp_path / "index.html").write_text("<html><body>Radio Sight</body></html>", encoding="utf-8")
    nodes = tmp_path / "nodes.json"
    nodes.write_bytes((CHECKER.parent.parent / "radio" / "nodes.json").read_bytes())

    async def state(socket):
        await socket.send('{"v":2,"type":"state","t":1763149512200}')

    asked = []

    def history(req):
        asked.append(req.query)
        return {"rows": [{"t": 1763149511000}] if rows else []}

    rows = True

    async def silent(socket):
        await socket.wait_closed()

    async def check_servers(port):
        async with serve(state, "127.0.0.1", 0) as ws:
            assert await run_checker(port, ws.sockets[0].getsockname()[1]) == (
                0, ["PASS web", "PASS nodes.json", "PASS proof.json", "PASS WebSocket", "PASS records", "PASS ask"],
            )
            assert asked[-1] == {"from_t": "1763149452200", "to_t": "1763149512200"}   # the board's minute
            nonlocal rows
            rows = False
            code, lines = await run_checker(port, ws.sockets[0].getsockname()[1])
            assert code == 1 and lines[-2].startswith("FAIL records: no records") and lines[-1] == "PASS ask"
        async with serve(silent, "127.0.0.1", 0) as ws:
            code, lines = await run_checker(port, ws.sockets[0].getsockname()[1])
            assert code == 1
            assert lines[-3] == "FAIL WebSocket: TimeoutError"
            assert lines[-2].startswith("FAIL records: no board time")

    with make_server("127.0.0.1", 0, dist=tmp_path, nodes=nodes, proof=tmp_path / "proof.json",
                     ask=lambda question: {"answer": "Nobody is here."},
                     routes={("GET", "/history"): history}) as board:
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
    assert [line.split(":", 1)[0] for line in lines] == [
        "FAIL web", "FAIL nodes.json", "FAIL proof.json", "FAIL WebSocket", "FAIL records", "FAIL ask",
    ]


def test_layout_counts_reject_a_different_layout():
    import pytest
    from scripts.demo_check import layout_counts
    with pytest.raises(ValueError, match="count differs"):
        layout_counts(b'{"nodes":[],"links":[]}')
