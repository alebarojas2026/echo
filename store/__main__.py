"""python -m store: follow the brain's WebSocket and save what it sends. See store/__init__.py."""
import argparse
import asyncio
import json
import sqlite3
import sys
import time

from . import DB, Store

WS_URL = "ws://127.0.0.1:8765/ws"
RETRY_S = 2.0
WARN_EVERY_S = 60.0   # a full disk is said once a minute, not once a message


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


class Keeper:
    """Saves one message from the brain at a time. A message that can't be read is skipped. When
    the database can't be written (a full disk), that row is dropped and the store keeps following,
    so it writes again by itself once there is room, instead of ending and crash-looping."""

    def __init__(self, store: Store, clock=time.monotonic, log=None):
        self.store, self.clock, self.dropped, self.warned_at = store, clock, 0, None
        self.log = log or (lambda text: print(text, file=sys.stderr, flush=True))

    def keep(self, raw) -> bool:
        try:
            return bool(self.store.add(json.loads(raw)))
        except ValueError:
            return False
        except sqlite3.Error as e:
            self.dropped += 1
            now = self.clock()
            if self.warned_at is None or now - self.warned_at >= WARN_EVERY_S:
                self.warned_at = now
                self.log(f"store: can't write ({e}); dropping rows until it can ({self.dropped} so far)")
            return False


async def follow(store: Store, url: str = WS_URL, retry_s: float = RETRY_S) -> None:
    """Save every state and event from the brain, reconnecting for ever."""
    import websockets
    keeper = Keeper(store)
    while True:
        try:
            async with websockets.connect(url) as ws:
                print(f"store: following {url}", file=sys.stderr, flush=True)
                async for raw in ws:
                    keeper.keep(raw)
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
