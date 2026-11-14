"""Wi-Fi signal reader for the UNO Q: the pi5>unoq:wifi link.

    python -m radio.wifi_rssi                 # sends rssi to the bus (127.0.0.1:5600); the service runs this
    python -m radio.wifi_rssi --seconds 30    # the same, then prints readings/s and the median dBm

Polls `iw dev <iface> station get <bssid>` RATE_HZ times a second and sends the signal of the last
frame heard from the Pi, but only when `rx packets` went up since the last poll, so the same frame
is never sent twice.

The Pi's hotspot sends only about 10 beacons a second, half of what Gate 1 needs. So the reader also
pings the hotspot's address (10.42.0.1, CONTRACTS.md section 2) PING_HZ times a second: every reply
is a fresh frame from the Pi to read.

When the board isn't joined to the hotspot yet (the Pi came up late, or rebooted), the reader keeps
trying and says so once in the log, instead of exiting.

Settings come from the environment (the service loads the repo's .env):
    WIFI_IFACE       the interface joined to the sensing hotspot (default wlan0)
    WIFI_BSSID       the Pi hotspot's BSSID (SENSING_BSSID also works). Never commit it.
    WIFI_PING_HOST   what to ping (default 10.42.0.1)
    WIFI_PING_HZ     pings a second (default 50); 0 turns the pings off
    BUS_HOST         bus UDP host (default 127.0.0.1)
    BUS_PORT         bus UDP port (default 5600)
    RATE_HZ          polls a second (default 25)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import socket
import statistics
import subprocess
import sys
import time

LINK_ID = "pi5>unoq:wifi"
TX = "pi5"
RX = "unoq"
KIND = "wifi"

_SIGNAL_RE = re.compile(r"signal:\s+(-?\d+)\s+dBm")
_RX_PACKETS_RE = re.compile(r"rx packets:\s+(\d+)")


def log(text: str) -> None:
    print(f"[wifi_rssi] {text}", flush=True)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def settings(environ=os.environ) -> dict:
    return {
        "iface": environ.get("WIFI_IFACE") or "wlan0",
        "bssid": environ.get("WIFI_BSSID") or environ.get("SENSING_BSSID") or "",
        "bus_host": environ.get("BUS_HOST") or "127.0.0.1",
        "bus_port": int(environ.get("BUS_PORT") or 5600),
        "rate_hz": float(environ.get("RATE_HZ") or 25),
        "ping_host": environ.get("WIFI_PING_HOST") or "10.42.0.1",
        "ping_hz": float(environ.get("WIFI_PING_HZ") or 50),
    }


# ---------------------------------------------------------------------------
# iw
# ---------------------------------------------------------------------------

def parse_station_output(text: str) -> tuple[int | None, int | None]:
    """Signal dBm and the rx packets counter from `iw ... station get` output."""
    m_sig = _SIGNAL_RE.search(text)
    m_rx = _RX_PACKETS_RE.search(text)
    dbm = int(m_sig.group(1)) if m_sig else None
    rx_pkts = int(m_rx.group(1)) if m_rx else None
    return dbm, rx_pkts


def _iw(*args: str) -> str | None:
    try:
        return subprocess.check_output(["iw", *args], stderr=subprocess.DEVNULL, timeout=0.5).decode()
    except Exception:
        return None


def _read_station_info(iface: str, bssid: str) -> tuple[int | None, int | None]:
    """(dbm, rx_packets), or (None, None) when there's no such station."""
    out = _iw("dev", iface, "station", "get", bssid)
    return parse_station_output(out) if out is not None else (None, None)


def _make_message(dbm: int, seq: int) -> bytes:
    msg = {
        "v": 2,
        "type": "rssi",
        "t": int(time.time() * 1000),
        "seq": seq,
        "src": "live",
        "link": LINK_ID,
        "kind": KIND,
        "tx": TX,
        "rx": RX,
        "dbm": dbm,
    }
    return json.dumps(msg, separators=(",", ":")).encode()


class Reader:
    """Turns polls into fresh readings: a poll counts only when rx packets went up since the last one."""

    def __init__(self, iface: str, bssid: str, read=_read_station_info, say=log):
        self.iface, self.bssid, self.read, self.say = iface, bssid, read, say
        self.prev_rx: int | None = None
        self.joined: bool | None = None

    def poll(self) -> int | None:
        """The signal of a frame heard since the last poll, or None."""
        dbm, rx = self.read(self.iface, self.bssid)
        if dbm is None or rx is None:
            self._joined(False)
            self.prev_rx = None  # a rejoin starts the station's counters again
            return None
        self._joined(True)
        fresh = self.prev_rx is not None and rx > self.prev_rx
        self.prev_rx = rx
        return dbm if fresh else None

    def _joined(self, now: bool) -> None:
        if now == self.joined:
            return
        if now:
            self.say(f"reading {LINK_ID} on {self.iface}")
        else:
            self.say(f"no signal: {self.iface} isn't joined to the Pi's hotspot; still trying")
        self.joined = now


class Pinger:
    """Keeps a `ping` to the Pi running, so the Pi sends a frame `hz` times a second."""

    def __init__(self, host: str, hz: float, popen=subprocess.Popen, clock=time.monotonic,
                 retry_s: float = 2.0, say=log):
        self.cmd = ["ping", "-n", "-q", "-i", f"{1.0 / hz:.3f}", host] if hz > 0 else None
        self.popen, self.clock, self.retry_s, self.say = popen, clock, retry_s, say
        self.proc = None
        self.next_try = 0.0

    def check(self) -> None:
        """Start ping if it isn't running (it exits while the hotspot is down), at most every retry_s."""
        if self.cmd is None or (self.proc is not None and self.proc.poll() is None):
            return
        now = self.clock()
        if now < self.next_try:
            return
        self.next_try = now + self.retry_s
        try:
            self.proc = self.popen(self.cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        except OSError as e:
            self.say(f"can't run ping ({e}); readings come at the beacon rate only")
            self.cmd = None

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None


# ---------------------------------------------------------------------------
# Loops
# ---------------------------------------------------------------------------

def poll_loop(reader: Reader, on_reading, rate_hz: float, seconds: float = 0, stop=lambda: False,
              tick=None, clock=time.monotonic, sleep=time.sleep) -> float:
    """Poll rate_hz times a second until `seconds` pass (0 = forever) or stop(). Returns the time spent.

    on_reading(dbm) gets every fresh reading; tick() runs after every poll.
    """
    interval = 1.0 / rate_hz
    start = clock()
    end = start + seconds if seconds else None
    next_tick = start
    while not stop() and (end is None or clock() < end):
        dbm = reader.poll()
        if dbm is not None:
            on_reading(dbm)
        if tick is not None:
            tick()
        next_tick += interval
        sleep_for = next_tick - clock()
        if sleep_for > 0:
            sleep(sleep_for)
        else:
            next_tick = clock()  # fell behind: don't spin trying to catch up
    return clock() - start


class Stats:
    """Readings per report period, for the log: a dead link shows up in journalctl."""

    def __init__(self, every_s: float = 10.0, clock=time.monotonic, say=log):
        self.every_s, self.clock, self.say = every_s, clock, say
        self.values: list[int] = []
        self.since = clock()

    def add(self, dbm: int) -> None:
        self.values.append(dbm)

    def tick(self) -> None:
        now = self.clock()
        if self.every_s <= 0 or now - self.since < self.every_s:
            return
        span = now - self.since
        if self.values:
            self.say(f"last {span:.0f} s: {len(self.values)} readings ({len(self.values) / span:.1f}/s), "
                     f"median {statistics.median(self.values):g} dBm")
        else:
            self.say(f"last {span:.0f} s: no readings")
        self.values, self.since = [], now


def summary(values: list[int], seconds: float) -> str:
    if not values:
        return f"{LINK_ID}: no readings in {seconds:.1f} s"
    return (f"{LINK_ID}: {len(values)} readings in {seconds:.1f} s = {len(values) / seconds:.1f}/s, "
            f"median {statistics.median(values):g} dBm")


def run(iface: str = "wlan0", bssid: str = "", bus_host: str = "127.0.0.1", bus_port: int = 5600,
        rate_hz: float = 25.0, *, seconds: float = 0, stop=lambda: False, ping_host: str = "10.42.0.1",
        ping_hz: float = 50.0, report_every: float = 10.0, reader: Reader | None = None,
        pinger: Pinger | None = None) -> list[int]:
    """Read and send to the bus until `seconds` pass (0 = forever) or stop(). Returns every dBm sent."""
    reader = reader or Reader(iface, bssid)
    pinger = pinger or Pinger(ping_host, ping_hz)
    stats = Stats(report_every)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # one socket, one seq counter
    sent: list[int] = []

    def send(dbm: int) -> None:
        try:
            sock.sendto(_make_message(dbm, len(sent)), (bus_host, bus_port))
        except OSError as e:
            log(f"send to the bus failed: {e}")
        sent.append(dbm)
        stats.add(dbm)

    def tick() -> None:
        pinger.check()
        stats.tick()

    log(f"polling {iface} {rate_hz:g} times a second -> {bus_host}:{bus_port}; "
        + (f"pinging {ping_host} {ping_hz:g} times a second" if pinger.cmd else "no pings"))
    pinger.check()
    try:
        poll_loop(reader, send, rate_hz, seconds, stop, tick)
    finally:
        pinger.stop()
        sock.close()
    return sent


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Wi-Fi signal reader for the pi5>unoq:wifi link")
    ap.add_argument("--seconds", type=float, default=0, help="stop after this long and print a summary")
    args = ap.parse_args(argv)

    cfg = settings()
    if shutil.which("iw") is None:
        sys.exit("wifi_rssi: iw isn't installed. Run: sudo apt install iw "
                 "(before the board joins the hotspot: there's no internet after)")
    if not cfg["bssid"]:
        sys.exit("wifi_rssi: WIFI_BSSID (or SENSING_BSSID) isn't set. Put it in the repo's .env, "
                 "never in the repo")
    reader = Reader(cfg["iface"], cfg["bssid"])
    pinger = Pinger(cfg["ping_host"], cfg["ping_hz"])
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))  # a service stop still stops the pings

    started = time.monotonic()
    sent: list[int] = []
    try:
        sent = run(cfg["iface"], cfg["bssid"], cfg["bus_host"], cfg["bus_port"], cfg["rate_hz"],
                   seconds=args.seconds, ping_host=cfg["ping_host"], ping_hz=cfg["ping_hz"],
                   reader=reader, pinger=pinger)
    except KeyboardInterrupt:
        pass
    if args.seconds:
        print(summary(sent, max(time.monotonic() - started, 1e-3)))


if __name__ == "__main__":
    main()
