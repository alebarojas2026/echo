"""The brain starts listening on an address that only comes up later (the board's Ethernet)."""
import asyncio
import errno
import json
import logging

from websockets.asyncio.client import connect

from brain import main

LATE = "127.0.0.2"   # stands in for 192.168.77.2


def test_brain_listens_on_a_late_address_without_a_restart(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="brain")
    calls = {"late": 0}
    real_serve = main.serve

    async def serve(handler, host, port):
        if host == LATE:
            calls["late"] += 1
            if calls["late"] <= 3:   # down at start, and for two retries
                raise OSError(errno.EADDRNOTAVAIL, "Cannot assign requested address")
            host = "127.0.0.1"       # "comes up": bind it on a second local port
            port = 0
        return await real_serve(handler, host, port)

    monkeypatch.setattr(main, "serve", serve)

    async def scenario():
        loop = asyncio.get_running_loop()
        ready, stop = loop.create_future(), asyncio.Event()
        task = asyncio.create_task(main.run(bus_in=("127.0.0.1", 0), ws_hosts=("127.0.0.1", LATE), ws_port=0,
                                            ready=ready, stop=stop, retry_s=0.05))
        ports = await ready
        async with connect(f"ws://127.0.0.1:{ports['ws']}/ws") as ws:   # 127.0.0.1 works straight away
            assert json.loads(await ws.recv())["type"] == "state"
        async with asyncio.timeout(5):
            while calls["late"] < 4:
                await asyncio.sleep(0.02)
        await asyncio.sleep(0.05)
        stop.set()
        await task

    asyncio.run(scenario())
    assert calls["late"] == 4                       # stops retrying once it binds
    text = [r.getMessage() for r in caplog.records]
    assert sum("is not up yet" in t for t in text) == 1          # logged once when it fails
    assert sum("now listening on 127.0.0.2" in t for t in text) == 1   # and once when it binds


def test_any_other_bind_error_still_fails_at_start(monkeypatch):
    async def serve(handler, host, port):
        raise OSError(errno.EADDRINUSE, "Address already in use")

    monkeypatch.setattr(main, "serve", serve)

    async def scenario():
        await main.run(bus_in=("127.0.0.1", 0), ws_hosts=("127.0.0.1",), ws_port=0)

    try:
        asyncio.run(scenario())
    except OSError as e:
        assert e.errno == errno.EADDRINUSE
    else:
        raise AssertionError("expected the bind error")
