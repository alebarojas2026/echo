"""End to end: fake feed -> UDP -> brain -> WebSocket -> a screen, and commands back."""
import asyncio
import json
import socket

from websockets.asyncio.client import connect

from brain import main
from brain.tests.simdata import T0_MS, sim_to_v2


def test_fake_feed_to_screen_end_to_end():
    asyncio.run(asyncio.wait_for(_scenario(), timeout=60))


async def _scenario():
    loop = asyncio.get_running_loop()
    bus = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)   # stands in for the bus's cmd port
    bus.bind(("127.0.0.1", 0))
    bus.setblocking(False)
    ready, stop = loop.create_future(), asyncio.Event()
    task = asyncio.create_task(main.run(bus_in=("127.0.0.1", 0), bus_out=bus.getsockname(),
                                        ws_hosts=("127.0.0.1",), ws_port=0, feed_clock=True,
                                        ready=ready, stop=stop))
    ports = await ready
    feed = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    clock = [T0_MS]

    async def play(path, seed=0, meta=None):
        msgs = sim_to_v2(path, seed=seed, meta=meta, t0=clock[0])
        for i, m in enumerate(msgs):
            feed.sendto(json.dumps(m).encode(), ("127.0.0.1", ports["udp"]))
            if i % 2 == 0:   # give the loop a turn every 2 messages (and a real pause every 20),
                await asyncio.sleep(0.001 if i % 20 == 0 else 0)   # so the brain's socket buffer never overflows
        clock[0] = msgs[-1]["recv_t"] + 100
        # Wait for the tail of it, with a deadline: a dropped datagram must not hang the test.
        nearly, deadline = msgs[-20]["recv_t"], loop.time() + 10
        while ports["brain"].feed_t < nearly:
            assert loop.time() < deadline, f"{path}: the brain got to {ports['brain'].feed_t}, not {nearly}"
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)

    async with connect(f"ws://127.0.0.1:{ports['ws']}/ws") as ws:
        seen = []

        async def until(test):
            while True:
                msg = json.loads(await ws.recv())
                seen.append(msg)
                if test(msg):
                    return msg

        async def send(cmd, **args):
            await ws.send(json.dumps({"v": 2, "type": "cmd", "cmd": cmd, "args": args}))
            await asyncio.sleep(0.05)

        first = await until(lambda m: m["type"] == "state")
        assert first["pred"] is None and first["model"]["trained"] is False

        # Section 1: anything that isn't v 2 is dropped, on both sides.
        await ws.send(json.dumps({"v": 1, "type": "cmd", "cmd": "record_start", "args": {"session": "old"}}))
        await ws.send(json.dumps({"type": "cmd", "cmd": "reset", "args": {}}))
        feed.sendto(json.dumps(dict(sim_to_v2("empty_room")[1], v=1)).encode(), ("127.0.0.1", ports["udp"]))
        await asyncio.sleep(0.3)
        assert ports["brain"].events == [] and ports["brain"].want_session is None
        assert (await until(lambda m: m["type"] == "state"))["links"] == []

        await send("baseline")
        await play("empty_room", seed=1)
        await until(lambda m: m["type"] == "event" and m["kind"] == "baseline_done")

        await send("record_start", session="s01", purpose="train", walker=None)
        await play("empty_room", seed=2, meta={"session": "s01", "purpose": "train", "walker": None})
        await send("record_stop")
        await send("record_start", session="s02", purpose="train", walker="w1")
        await play("zone_tour", seed=3, meta={"session": "s02", "purpose": "train", "walker": "w1"})
        await send("record_stop")
        await send("train")
        await until(lambda m: m["type"] == "event" and m["kind"] == "trained")

        await play("stand_still", seed=4)   # walks into a zone, stands, walks out
        await until(lambda m: m["type"] == "state" and m["model"]["trained"])
        brain = ports["brain"]
        assert brain.model.info()["train_sessions"] == ["s01", "s02"]
        assert brain.pred is not None and brain.pred["present"] is False   # they walked out

        state = seen[-1]
        assert state["src"] == "sim" and state["links"][0]["base_dbm"] is not None
        assert state["model"]["ms_per_decision"] is not None

        # Everything arrives in seq order: events go out before the state that follows them.
        seqs = [m["seq"] for m in seen]
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
        assert {m["kind"] for m in seen if m["type"] == "event"} >= {"baseline_done", "recording", "trained"}

        # A second screen that never reads doesn't hold this one up.
        idle = await connect(f"ws://127.0.0.1:{ports['ws']}/ws", max_queue=1, close_timeout=0.2)

        # States arrive about 10 times a second.
        await until(lambda m: m["type"] == "state" and m["seq"] >= brain._seq)  # skip the backlog
        t0 = loop.time()
        for _ in range(10):
            await until(lambda m: m["type"] == "state")
        assert 0.5 < loop.time() - t0 < 2.0

        await idle.close()

    # The commands reached the bus port, in order, as v2 cmd messages.
    got = []
    while True:
        try:
            got.append(json.loads(bus.recv(65535)))
        except BlockingIOError:
            break
    assert [m["cmd"] for m in got] == ["baseline", "record_start", "record_stop", "record_start", "record_stop", "train"]
    assert all(m["v"] == 2 and m["type"] == "cmd" for m in got)

    stop.set()
    await task
    feed.close()
    bus.close()
