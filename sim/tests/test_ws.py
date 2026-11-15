import asyncio
import json

import pytest
import websockets

from contracts.check import errors
from sim import fake, ws
from sim.tests.conftest import schema_fits
from sim.tests.test_state import UNMEASURED


@pytest.fixture(autouse=True)
def _on_the_square(square):
    """These tests check the server with the square's points and numbers, so they pin the square
    (sim/tests/conftest.py) whichever layout radio/nodes.json holds."""


STILL = {"name": "t", "duration_s": 30, "person": [{"t": 0, "x": 1.5, "y": 0.5}]}  # zone 4, 10 s limit


async def session(path, client, speed=20.0, loop=False):
    """Start a server on a free port, run `client(url, server)` against it, stop the server."""
    server = ws.Server(path, speed=speed, loop=loop)
    port = asyncio.get_running_loop().create_future()
    task = asyncio.create_task(server.serve("127.0.0.1", 0, ready=port.set_result))
    try:
        return await asyncio.wait_for(client(f"ws://127.0.0.1:{await port}", server), timeout=20)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def read(sock, n):
    return [json.loads(await sock.recv()) for _ in range(n)]


def test_defaults_are_the_brain_address_from_the_contract():
    assert (ws.HOST, ws.PORT, ws.PATH) == ("127.0.0.1", 8765, "/ws")


def test_screen_gets_valid_state_and_events_in_order(square):
    async def client(url, server):
        async with websockets.connect(url + "/ws") as sock:
            return await read(sock, 100)  # about 10 s of the tour, past the first zone change

    msgs = asyncio.run(session(fake.load_path("zone_tour"), client))
    assert not schema_fits(square) or all(set(errors(m)) <= UNMEASURED for m in msgs)
    assert {m["type"] for m in msgs} == {"state", "event"} and {m["src"] for m in msgs} == {"sim"}
    seqs = [m["seq"] for m in msgs]
    assert seqs == list(range(seqs[0], seqs[0] + 100))
    states = [m for m in msgs if m["type"] == "state"]
    gaps = {b["t"] - a["t"] for a, b in zip(states, states[1:])}
    assert gaps == {100}  # ten states a second on the message clock


def test_two_screens_get_the_same_messages():
    async def client(url, server):
        async with websockets.connect(url + "/ws") as a, websockets.connect(url + "/ws") as b:
            first, second = await read(a, 30), await read(b, 30)
        return first, second

    first, second = asyncio.run(session(fake.load_path("zone_tour"), client))
    shared = {m["seq"] for m in first} & {m["seq"] for m in second}
    assert len(shared) > 10
    assert [m for m in first if m["seq"] in shared] == [m for m in second if m["seq"] in shared]


def test_reset_alert_command_clears_the_alert():
    async def client(url, server):
        async with websockets.connect(url + "/ws") as sock:
            seen, sent = [], False
            while True:
                m = json.loads(await sock.recv())
                if m["type"] != "state":
                    continue
                seen.append(m["alert"]["state"])
                if m["alert"]["state"] == "check_on" and not sent:
                    sent = True   # decided here, not from what the server has read so far
                    await sock.send("not json")
                    await sock.send(json.dumps({"v": 1, "type": "cmd", "cmd": "reset_alert", "args": {}}))
                    await sock.send(json.dumps({"v": 2, "type": "cmd", "cmd": "reset_alert", "args": {}}))
                if sent and m["alert"]["state"] == "counting":
                    return seen, server.commands

    seen, commands = asyncio.run(session(STILL, client))
    assert "check_on" in seen and seen[-1] == "counting"
    assert [c["cmd"] for c in commands] == ["reset_alert"]  # bad JSON and v1 were skipped


def test_wrong_path_is_refused():
    async def client(url, server):
        try:
            async with websockets.connect(url + "/other") as sock:
                await sock.recv()
        except websockets.ConnectionClosed as closed:
            return closed.rcvd.code, len(server.clients)

    assert asyncio.run(session(fake.load_path("zone_tour"), client)) == (1008, 0)


def test_loop_keeps_seq_and_event_ids_going():
    short = {"name": "t", "duration_s": 3, "person": [{"t": 0, "x": 0.5, "y": 0.5}]}

    async def client(url, server):
        async with websockets.connect(url + "/ws") as sock:
            return await read(sock, 80)  # more than two 3 s loops (30 states and 3 events each)

    msgs = asyncio.run(session(short, client, loop=True))
    seqs = [m["seq"] for m in msgs]
    assert seqs == list(range(seqs[0], seqs[0] + 80))
    events = [m for m in msgs if m["type"] == "event"]
    assert [e["kind"] for e in events].count("trained") >= 2   # it really did start over
    assert len({e["id"] for e in events}) == len(events)


def test_reset_command_clears_checkin_and_shows_the_recap():
    async def client(url, server):
        async with websockets.connect(url + "/ws") as sock:
            sent = False
            while True:
                m = json.loads(await sock.recv())
                if m["type"] != "state":
                    continue
                if m["checkin"] and not sent:
                    sent = True
                    await sock.send(json.dumps({"v": 2, "type": "cmd", "cmd": "reset", "args": {}}))
                elif sent and m["checkin"] is None:
                    return m["narration"], [c["cmd"] for c in server.commands]

    narration, commands = asyncio.run(session(fake.load_path("wave_checkin"), client))
    assert commands == ["reset"] and narration["text"].startswith("Someone visited")   # the recap
