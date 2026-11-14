"""One bad message or one failed tick must not stop the brain."""
import asyncio
import json
import logging
import socket

from websockets.asyncio.client import connect

from brain import main
from brain.tests.simdata import T0_MS


def test_a_malformed_reading_and_a_failed_tick_do_not_stop_the_loop(caplog):
    caplog.set_level(logging.ERROR, logger="brain")
    main._complained.clear()

    async def scenario():
        loop = asyncio.get_running_loop()
        ready, stop = loop.create_future(), asyncio.Event()
        task = asyncio.create_task(main.run(bus_in=("127.0.0.1", 0), ws_hosts=("127.0.0.1",), ws_port=0,
                                            feed_clock=True, ready=ready, stop=stop))
        ports = await asyncio.wait_for(ready, 5)
        brain, feed = ports["brain"], socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        def send(**fields):
            msg = {"v": 2, "type": "rssi", "recv_t": T0_MS, "src": "sim", "link": "pi5>unoq:wifi", **fields}
            feed.sendto(json.dumps(msg).encode(), ("127.0.0.1", ports["udp"]))

        async with connect(f"ws://127.0.0.1:{ports['ws']}/ws") as ws:
            for _ in range(5):
                send(dbm=None)                       # a reader bug: no number
                send(dbm="loud")
            send(dbm=-50, recv_t=T0_MS + 100)        # and a good one after them
            real_state, calls = brain.state, {"n": 0}

            def flaky():
                calls["n"] += 1
                if calls["n"] <= 3:
                    raise RuntimeError("boom")
                return real_state()

            brain.state = flaky
            async with asyncio.timeout(5):
                while True:
                    msg = json.loads(await ws.recv())
                    if msg["type"] == "state" and calls["n"] > 3 and msg["links"]:
                        break
            assert msg["links"][0]["id"] == "pi5>unoq:wifi" and msg["links"][0]["dbm"] == -50
        assert not task.done()
        stop.set()
        await task
        feed.close()

    asyncio.run(scenario())
    said = [r.getMessage() for r in caplog.records]
    assert sum("a state tick failed" in t for t in said) == 1          # logged, but not on every tick
    assert sum("could not be used" in t for t in said) == 1
