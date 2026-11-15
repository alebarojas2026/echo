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
        await socket.send('{"v":2,"type":"state"}')

    async def silent(socket):
        await socket.wait_closed()

    async def check_servers(port):
        async with serve(state, "127.0.0.1", 0) as ws:
            assert await run_checker(port, ws.sockets[0].getsockname()[1]) == (
                0, ["PASS web", "PASS nodes.json", "PASS proof.json", "PASS WebSocket"],
            )
        async with serve(silent, "127.0.0.1", 0) as ws:
            code, lines = await run_checker(port, ws.sockets[0].getsockname()[1])
            assert code == 1
            assert lines[-1] == "FAIL WebSocket: TimeoutError"

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
    assert [line.split(":", 1)[0] for line in lines] == [
        "FAIL web", "FAIL nodes.json", "FAIL proof.json", "FAIL WebSocket",
    ]


def test_layout_counts_reject_a_different_layout():
    import pytest
    from scripts.demo_check import layout_counts
    with pytest.raises(ValueError, match="count differs"):
        layout_counts(b'{"nodes":[],"links":[]}')
