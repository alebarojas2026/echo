"""End to end with no hardware: sim -> bus -> brain -> screen WebSocket.

Starts the bus and the brain on spare ports, plays the zone tour and the metal object through
sim.send at high speed, and checks what a screen would get: every message follows the contract,
state comes about 10 times a second, and events arrive.
"""
import asyncio
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from contracts.check import errors

REPO = Path(__file__).resolve().parents[2]
SPEED = 10  # sim.send runs the paths this many times faster than real time

pytestmark = pytest.mark.skipif(not (REPO / "brain" / "main.py").exists(),
                                reason="brain.main (the live loop) is not on main yet, see PRs #101 and #102")


def spare_port(kind=socket.SOCK_DGRAM):
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(log, *args):
    with open(log, "w") as out:
        return subprocess.Popen([sys.executable, "-m", *args], cwd=REPO, stdout=out, stderr=subprocess.STDOUT)


def wait_for(text, log, proc, seconds=10):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if text in log.read_text():
            return
        assert proc.poll() is None, f"{log.name} exited:\n{log.read_text()}"
        time.sleep(0.1)
    raise AssertionError(f"no {text!r} in {log.name} after {seconds} s:\n{log.read_text()}")


async def screen(ws_port, bus_port):
    """Act as a screen while the sim plays. Returns [(arrival s, message)]."""
    from websockets.asyncio.client import connect

    url, end = f"ws://127.0.0.1:{ws_port}/ws", time.monotonic() + 30
    while True:  # the brain takes a moment to load
        try:
            ws = await connect(url)
            break
        except OSError:
            assert time.monotonic() < end, "brain WebSocket never came up"
            await asyncio.sleep(0.2)
    got = []

    async def listen():
        async for raw in ws:
            got.append((time.monotonic(), json.loads(raw)))

    listener = asyncio.create_task(listen())
    await ws.send(json.dumps({"v": 2, "type": "cmd", "cmd": "reset", "args": {}}))
    for path in ("zone_tour", "metal_object"):
        sim = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "sim.send", path, "--host", "127.0.0.1", "--port", str(bus_port),
            "--speed", str(SPEED), cwd=REPO)
        assert await sim.wait() == 0, f"sim.send {path} failed"
    await asyncio.sleep(1)
    listener.cancel()
    await ws.close()
    return got


def test_sim_through_bus_and_brain_to_screen(tmp_path):
    pytest.importorskip("websockets", reason="the screen side of this test needs websockets")
    bus_port, brain_port, ws_port = spare_port(), spare_port(), spare_port(socket.SOCK_STREAM)
    bus_log, brain_log = tmp_path / "bus.log", tmp_path / "brain.log"
    procs = [start(bus_log, "bus", "--host", "127.0.0.1", "--port", str(bus_port),
                   "--forward", f"127.0.0.1:{brain_port}", "--sessions", str(tmp_path)),
             start(brain_log, "brain.main", "--bus-port", str(brain_port), "--ws-port", str(ws_port),
                   "--ws-host", "127.0.0.1", "--mode-file", str(tmp_path / "label_mode"))]
    try:
        wait_for("listening on", bus_log, procs[0])
        got = asyncio.run(screen(ws_port, bus_port))
    finally:
        for p in procs:
            p.terminate()
            p.wait(timeout=10)
    logs = f"\nbus:\n{bus_log.read_text()[-2000:]}\nbrain:\n{brain_log.read_text()[-2000:]}"

    bad = [(m.get("type"), err) for _, m in got for err in errors(m)]
    assert not bad, f"{len(bad)} contract errors, first ones: {bad[:10]}{logs}"
    states = [(t, m) for t, m in got if m["type"] == "state"]
    events = [m for _, m in got if m["type"] == "event"]
    assert {m["type"] for _, m in got} <= {"state", "event"}

    assert len(states) > 20, f"only {len(states)} states{logs}"
    rate = (len(states) - 1) / (states[-1][0] - states[0][0])
    assert 7 <= rate <= 13, f"state came {rate:.1f} times a second, not about 10"
    assert any(m["src"] == "sim" and any(link["rate_hz"] > 0 for link in m["links"]) for _, m in states), \
        f"no state shows the sim feed reaching the brain through the bus{logs}"
    assert events, f"no events arrived{logs}"
