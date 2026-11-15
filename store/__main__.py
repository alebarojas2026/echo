"""python -m store: follow the brain's WebSocket and save what it sends. See store/__init__.py."""
import argparse
import asyncio
import json
import sys
import time

from . import DB, Store

WS_URL = "ws://127.0.0.1:8765/ws"
RETRY_S = 2.0


def fill_from_sim(store: Store, path_name: str, end_ms=None, seed: int = 0) -> int:
    """Run a simulated path through the fake brain and save it, timed so it ends at end_ms
    (now by default). Returns the rows written. Every row carries src "sim"."""
    from sim import fake
    from sim.state import run
    from sim.wire import encoder
    messages = list(run(fake.load_path(path_name), seed=seed))
    end_ms = int(time.time() * 1000) if end_ms is None else end_ms
    encode = encoder(end_ms - round(messages[-1]["t"] * 1000))
    return sum(store.add(json.loads(encode(m))) for m in messages)


async def follow(store: Store, url: str = WS_URL, retry_s: float = RETRY_S) -> None:
    """Save every state and event from the brain, reconnecting for ever."""
    import websockets
    while True:
        try:
            async with websockets.connect(url) as ws:
                print(f"store: following {url}", file=sys.stderr, flush=True)
                async for raw in ws:
                    try:
                        store.add(json.loads(raw))
                    except ValueError:
                        continue
        except (OSError, websockets.WebSocketException) as e:
            print(f"store: no brain at {url} ({e}); retrying", file=sys.stderr, flush=True)
        await asyncio.sleep(retry_s)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Save the brain's events and a once-a-second summary of state")
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--ws", default=WS_URL, help="the brain's WebSocket")
    ap.add_argument("--sim", metavar="PATH", help="fill from a simulated path (sim/paths/) and exit")
    args = ap.parse_args(argv)
    store = Store(args.db)
    if args.sim:
        print(f"store: {fill_from_sim(store, args.sim)} rows from the simulated path {args.sim} in {args.db}")
        return
    try:
        asyncio.run(follow(store, args.ws))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
