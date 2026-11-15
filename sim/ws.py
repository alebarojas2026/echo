"""Serve the fake brain on the brain's WebSocket, so the screen runs with no board and no brain.

    python -m sim.ws demo --loop             # ws://127.0.0.1:8765/ws
    python -m sim.ws wave_checkin --speed 2

Every connected screen gets the same `state` and `event` messages (CONTRACTS.md section 5,
src "sim") at real speed. `cmd` messages from the screen are read: reset_alert clears the
alert, reset also clears the still timer, check-in and advice, sends the `reset` event and puts
the template end-of-demo recap in the narration (and disarms), `arm {on}` arms or disarms
(section 6, Armed), and the rest are accepted and ignored. Needs websockets 14 or newer.
"""
import argparse
import asyncio
import json
import time

import websockets

from . import fake
from .state import Brain, run
from .wire import encoder

HOST, PORT, PATH = "127.0.0.1", 8765, "/ws"


class Server:
    def __init__(self, path: dict, rate: float = 15.0, seed: int = 0, speed: float = 1.0, loop: bool = False):
        self.path, self.rate, self.seed, self.speed, self.loop = path, rate, seed, speed, loop
        self.clients, self.commands, self.brain = set(), [], None
        self.encode = encoder()   # one producer: seq keeps counting across loops

    async def screen(self, ws) -> None:
        """One connected screen: keep it in the broadcast set and read its commands."""
        if ws.request.path != PATH:
            await ws.close(1008, f"connect to {PATH}")
            return
        self.clients.add(ws)
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(msg, dict) and msg.get("v") == 2 and msg.get("type") == "cmd":
                    self.commands.append(msg)
                    if self.brain:
                        self.brain.command(msg)
        except websockets.ConnectionClosed:
            pass
        finally:
            self.clients.discard(ws)

    async def play(self) -> None:
        """Send the path's messages to every screen at real speed; again and again with loop."""
        events_so_far = 0
        while True:
            start_ms, started = int(time.time() * 1000), time.monotonic()
            self.brain = Brain(self.path, self.rate, start_ms)
            self.brain.n_events = events_so_far   # event ids stay unique across loops
            for m in run(self.path, rate=self.rate, seed=self.seed, brain=self.brain):
                wait = m["t"] / self.speed - (time.monotonic() - started)
                await asyncio.sleep(max(0.0, wait))   # always yields, so commands get read
                websockets.broadcast(self.clients, self.encode({**m, "t": m["t"] + start_ms / 1000}))
            events_so_far = self.brain.n_events
            if not self.loop:
                return

    async def serve(self, host: str = HOST, port: int = PORT, ready=None) -> None:
        async with websockets.serve(self.screen, host, port) as server:
            if ready:
                ready(server.sockets[0].getsockname()[1])
            await self.play()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("path", help="path name in sim/paths/ or a path JSON file")
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--rate", type=float, default=15.0, help="radio readings per link per second")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--speed", type=float, default=1.0, help="2 = twice as fast")
    ap.add_argument("--loop", action="store_true", help="start over at the end, forever")
    args = ap.parse_args(argv)
    server = Server(fake.load_path(args.path), args.rate, args.seed, args.speed, args.loop)
    try:
        asyncio.run(server.serve(args.host, args.port,
                                 ready=lambda port: print(f"fake brain on ws://{args.host}:{port}{PATH}", flush=True)))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
