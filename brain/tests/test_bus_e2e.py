"""The real bus and the real brain on spare ports: baseline, record a session, train.

Slow (about 35 s): the baseline is 20 s of wall-clock time, because the bus stamps recv_t.
"""
import asyncio
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

from websockets.asyncio.client import connect

REPO = Path(__file__).resolve().parents[2]


def spare_port(kind=socket.SOCK_DGRAM):
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(log, *args):
    with open(log, "w") as out:
        return subprocess.Popen([sys.executable, "-m", *args], cwd=REPO, stdout=out, stderr=subprocess.STDOUT)


def test_record_and_train_through_the_real_bus(tmp_path):
    bus_port, brain_port, ws_port = spare_port(), spare_port(), spare_port(socket.SOCK_STREAM)
    procs = [start(tmp_path / "bus.log", "bus", "--host", "127.0.0.1", "--port", str(bus_port),
                   "--forward", f"127.0.0.1:{brain_port}", "--sessions", str(tmp_path)),
             start(tmp_path / "brain.log", "brain.main", "--bus-port", str(brain_port),
                   "--bus", f"127.0.0.1:{bus_port}", "--ws-port", str(ws_port), "--ws-host", "127.0.0.1",
                   "--sessions", str(tmp_path), "--mode-file", str(tmp_path / "label_mode"))]

    def feed(*args):
        return subprocess.Popen([sys.executable, "-m", "sim.send", *args, "--host", "127.0.0.1",
                                 "--port", str(bus_port)], cwd=REPO, stdout=subprocess.DEVNULL)

    async def screen():
        end = time.monotonic() + 30
        while True:   # the brain takes a moment to load
            try:
                ws = await connect(f"ws://127.0.0.1:{ws_port}/ws")
                break
            except OSError:
                assert time.monotonic() < end, "brain WebSocket never came up"
                await asyncio.sleep(0.2)

        async def send(cmd, **args):
            await ws.send(json.dumps({"v": 2, "type": "cmd", "cmd": cmd, "args": args}))

        async def until(test, seconds):
            async with asyncio.timeout(seconds):
                while True:
                    msg = json.loads(await ws.recv())
                    if test(msg):
                        return msg

        empty = feed("empty_room", "--loop")
        procs.append(empty)
        await until(lambda m: m["type"] == "state" and len(m["links"]) == 6 and m["cam"] == "on", 10)
        await send("baseline")
        await until(lambda m: m["type"] == "event" and m["kind"] == "baseline_done", 30)
        empty.terminate()

        await send("record_start", session="s1", purpose="train", walker="w1")
        tour = feed("zone_tour", "--speed", "4")
        procs.append(tour)
        await until(lambda m: m["type"] == "event" and m["kind"] == "recording" and m["info"]["on"], 5)
        assert await asyncio.to_thread(tour.wait) == 0
        await send("record_stop")
        await send("train")
        await until(lambda m: m["type"] == "event" and m["kind"] == "trained", 30)
        state = await until(lambda m: m["type"] == "state" and m["model"]["trained"], 5)
        await ws.close()
        return state

    try:
        state = asyncio.run(screen())
    finally:
        for p in procs:
            p.terminate()
            p.wait(timeout=10)
    logs = "".join(f"\n{name}:\n{(tmp_path / name).read_text()[-1500:]}" for name in ("bus.log", "brain.log"))

    assert state["model"]["train_sessions"] == ["s1"] and state["model"]["windows"] > 30, logs
    recorded = (tmp_path / "s1.jsonl").read_text().splitlines()      # the bus got our record_start
    assert json.loads(recorded[0])["type"] == "meta" and len(recorded) > 500, logs
    baseline = json.loads((tmp_path / "baseline.json").read_text())
    assert len(baseline["links"]) == 6, logs
    assert (tmp_path / "label_mode").read_text() == "off\n"
