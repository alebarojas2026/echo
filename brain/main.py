"""The brain's live loop (CONTRACTS.md v2, sections 2 and 5).

    python -m brain.main

Reads bus messages on UDP 127.0.0.1:5601, sends state about 10 times a second
(and events as they happen) to every screen on ws://<host>:8765/ws, and takes
cmd messages back from the screens. Commands are also passed to the bus on
127.0.0.1:5600 so it can record them.

    --feed-clock    time follows the feed's recv_t, not the wall clock
                    (for a recorded file played faster than real time)
"""
import argparse
import asyncio
import json
import logging
import os
import socket
from pathlib import Path

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from brain.alert import led_grid
from brain.core import Brain, now_ms

WS_HOSTS = ("127.0.0.1", "192.168.77.2")
STATE_EVERY_S = 0.1
log = logging.getLogger("brain")


def board_stats() -> dict:
    """CPU temperature, clock and load from Linux; None where it can't be read."""
    def read(path, scale):
        try:
            return round(int(Path(path).read_text().split()[0]) / scale, 1)
        except (OSError, ValueError, IndexError):
            return None
    try:
        pct = round(min(100.0, 100.0 * os.getloadavg()[0] / (os.cpu_count() or 1)))
    except OSError:
        pct = None
    return {"cpu_temp_c": read("/sys/class/thermal/thermal_zone0/temp", 1000),
            "cpu_mhz": read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq", 1000),
            "cpu_pct": pct}


class _BusIn(asyncio.DatagramProtocol):
    def __init__(self, brain: Brain):
        self.brain = brain

    def datagram_received(self, data, addr):
        try:
            msg = json.loads(data)
        except (ValueError, UnicodeDecodeError):
            return
        if isinstance(msg, dict):
            self.brain.on_message(msg)


async def run(bus_in=("127.0.0.1", 5601), bus_out=("127.0.0.1", 5600), ws_hosts=WS_HOSTS, ws_port=8765,
              mode_file=None, feed_clock=False, ready=None, stop=None):
    """Run until `stop` (an asyncio.Event) is set. `ready` gets the ports actually bound."""
    loop = asyncio.get_running_loop()
    out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    clients = set()

    def to_bus(msg):
        try:
            out.sendto(json.dumps(msg, separators=(",", ":")).encode(), bus_out)
        except OSError as e:
            log.warning("could not reach the bus: %s", e)

    brain = Brain(clock=None if feed_clock else now_ms, to_bus=to_bus, mode_file=mode_file,
                  spawn=lambda job: loop.run_in_executor(None, job), board_stats=board_stats,
                  led=led_grid())
    udp, _ = await loop.create_datagram_endpoint(lambda: _BusIn(brain), local_addr=bus_in)

    async def screen(ws):
        clients.add(ws)
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(msg, dict) and msg.get("type") == "cmd":
                    brain.on_cmd(msg)
        except ConnectionClosed:
            pass
        finally:
            clients.discard(ws)

    servers = []
    for host in ws_hosts:
        try:
            servers.append(await serve(screen, host, ws_port))
        except OSError as e:  # 192.168.77.2 only exists on the board
            log.warning("not listening on %s:%s (%s)", host, ws_port, e)
    if not servers:
        raise OSError(f"could not listen on any of {ws_hosts}")
    if ready is not None:
        ready.set_result({"udp": udp.get_extra_info("sockname")[1],
                          "ws": servers[0].sockets[0].getsockname()[1], "brain": brain})
    log.info("brain up: bus in %s, screens on port %s", bus_in, ws_port)

    stop = stop or asyncio.Event()
    try:
        while not stop.is_set():
            lines = [json.dumps(m, separators=(",", ":")) for m in [brain.state(), *brain.pop_events()]]
            for ws in list(clients):
                try:
                    for line in lines:
                        await ws.send(line)
                except ConnectionClosed:
                    clients.discard(ws)
            await asyncio.sleep(STATE_EVERY_S)
    finally:
        for s in servers:
            s.close()
        udp.close()
        out.close()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Radio Sight brain: live loop")
    ap.add_argument("--bus-port", type=int, default=5601)
    ap.add_argument("--ws-port", type=int, default=8765)
    ap.add_argument("--ws-host", action="append", help="address to listen on (repeatable)")
    ap.add_argument("--mode-file", default=os.environ.get("TEACHER_MODE_FILE"),
                    help="file the camera teacher reads its label mode from")
    ap.add_argument("--feed-clock", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    try:
        asyncio.run(run(bus_in=("127.0.0.1", args.bus_port), ws_hosts=tuple(args.ws_host or WS_HOSTS),
                        ws_port=args.ws_port, mode_file=args.mode_file, feed_clock=args.feed_clock))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
