"""A laptop as one more Wi-Fi line across the spot: pi5><node>:wifi.

    python3 -m radio.laptop_line --node laptop1                # on a laptop joined to the sensing hotspot
    python3 -m radio.laptop_line --node laptop1 --seconds 10   # the same, then prints readings/s and the median dBm
    python3 -m radio.laptop_line --node laptop1 --dry          # reads and prints the status line, sends nothing
    python3 -m radio.laptop_line --node laptop1 --fake         # no radio: a made-up line, sent as src "sim"

A laptop on Pi A's hotspot is a Wi-Fi client like Pi B is, so its own reading of that signal is one
more line across the spot. Several laptops along the far desk give several lines: each runs this with
its own --node (laptop1, laptop2, ...; the layout file says where each one stands). It asks the
operating system for one number, the signal strength of the network the laptop is joined to, and
sends it to the board's bus (UDP 192.168.77.2:5600) as an ordinary rssi message (CONTRACTS.md
section 4), the same shape radio/wifi_rssi.py sends for Pi B.

What it reads, and what it does not: only this laptop's own signal reading. It never asks for the
network's name or the access point's address, never scans, never listens to other devices, and sends
nothing but {v, type, t, seq, src, link, kind, tx, rx, dbm}. No admin rights, nothing to install:
the Python standard library is all it needs (Python 3.8 or newer, so a Mac's own /usr/bin/python3 will do).

How the number is read, 10 times a second:
- macOS: CoreWLAN's rssiValue of the Wi-Fi interface. No Location Services prompt (that permission
  guards the network's name and address, which are never asked for). Inside this Python when pyobjc
  is there; when it is not (a Mac's own python3 has none), one `osascript` is kept running that
  reads the same value and prints it. macOS refreshes the value about once every 1 to 2 s (measured
  on the kit: 9.3 readings a second arrive, in steps).
- Linux: /proc/net/wireless (the level column); where the kernel has no such file, `iw dev <if> link`.
- Windows: not supported. Another system is a class with read() and close(), listed in SOURCES.
Every poll is sent, so a line's rate stays steady for the brain's stale rule.

To keep the reading fresh it pings the board with the system's ping (--ping-hz, 0 = off): each reply
is a frame from the hotspot to measure. 10 a second on macOS; 5 a second on Linux, the fastest every
ping allows without root.

It keeps going when things around it fail:
- Wi-Fi off, or not joined: no reading, nothing is sent, the status line says so, it keeps trying;
- joined to another network (the laptop has no address on the sensing hotspot, 10.42.0.0/24): nothing
  is sent, since that would be another access point's signal. --net any switches the check off;
- the board is away: the datagrams are lost, and they arrive again when it is back (UDP, one socket);
- osascript or ping exits: it is started again.
Once a second it prints one status line (rate, last dBm). Ctrl-C stops it.

Settings: BUS_HOST (default 192.168.77.2) and BUS_PORT (default 5600) from the environment, or --bus.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import random
import re
import shutil
import signal
import socket
import statistics
import subprocess
import sys
import threading
import time

NODE = "laptop1"                 # --node: which laptop this is, a node id of the layout file
TX = "pi5"                       # the hotspot (Pi A)
NODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
BUS_HOST = "192.168.77.2"
BUS_PORT = 5600
HOTSPOT_NET = "10.42.0.0/24"     # CONTRACTS.md section 2: Pi A's hotspot
RATE_HZ = 10.0                   # polls a second
PING_HZ = 10.0                   # pings to the board a second
STATUS_S = 1.0
FRESH_S = 0.5                    # a value printed by osascript longer ago than this is no reading
RESTART_S = 2.0

# Measured with a laptop 50 cm east of Pi B (issue #95, check h): what the fake source imitates.
FAKE_HZ = 9.3                    # readings a second
FAKE_EMPTY_DBM = -49
FAKE_DROP_DB = 8                 # a person on the spot took 7 to 9 dB off
FAKE_SPREAD_DB = 0.5             # the empty line's spread
FAKE_HOLD_S = (1.0, 2.0)         # how long macOS keeps one value


def log(text: str) -> None:
    print(f"[laptop_line] {text}", flush=True)


def link_for(node: str) -> str:
    """The link id of this laptop's line: pi5><node>:wifi. Raises ValueError for a name that is no node id."""
    if not NODE_RE.match(node or ""):
        raise ValueError(f"--node {node!r} is not a node id like laptop1 (small letters, digits, _)")
    return f"{TX}>{node}:wifi"


LINK_ID = link_for(NODE)


def link_parts(link_id: str) -> tuple:
    """(tx, rx, kind) from "<tx>><rx>:<kind>". Raises ValueError for anything but a wifi link id."""
    ends, _, kind = link_id.partition(":")
    tx, _, rx = ends.partition(">")
    if not (tx and rx and kind == "wifi") or ">" in rx:
        raise ValueError(f"{link_id!r} is not a link id like pi5>laptop1:wifi")
    return tx, rx, kind


def make_message(dbm: int, seq: int, link_id: str = LINK_ID, src: str = "live", now=time.time) -> bytes:
    tx, rx, kind = link_parts(link_id)
    msg = {"v": 2, "type": "rssi", "t": int(now() * 1000), "seq": seq, "src": src,
           "link": link_id, "kind": kind, "tx": tx, "rx": rx, "dbm": dbm}
    return json.dumps(msg, separators=(",", ":")).encode()


def as_dbm(value) -> int | None:
    """A signal reading as whole dBm, or None: 0 and anything above it is what the system gives
    when Wi-Fi is off or not joined."""
    try:
        dbm = int(float(value))
    except (TypeError, ValueError):
        return None
    return dbm if -120 <= dbm < 0 else None


# ---------------------------------------------------------------------------
# Sources: read() gives the signal now in dBm, or None when there is none. close() lets go.
# ---------------------------------------------------------------------------

class Unsupported(Exception):
    """This source can't run here; the words say why."""


class CoreWLANSource:
    """macOS, inside this Python: CoreWLAN through pyobjc."""

    name = "pyobjc"
    src = "live"

    def __init__(self, platform: str = sys.platform):
        if platform != "darwin":
            raise Unsupported("CoreWLAN is macOS only")
        try:
            try:
                from CoreWLAN import CWWiFiClient
            except ImportError:
                import objc   # pyobjc-core without the CoreWLAN wrapper: load the framework by hand
                found = {}
                objc.loadBundle("CoreWLAN", found, bundle_path="/System/Library/Frameworks/CoreWLAN.framework")
                CWWiFiClient = found["CWWiFiClient"]
            self._client = CWWiFiClient.sharedWiFiClient()
        except Exception as e:   # no pyobjc in this Python, or the framework would not load
            raise Unsupported(f"pyobjc's CoreWLAN is not in this Python ({type(e).__name__})") from None

    def read(self) -> int | None:
        try:
            iface = self._client.interface()
            return None if iface is None else as_dbm(iface.rssiValue())
        except Exception:
            return None

    def close(self) -> None:
        pass


# One osascript that stays running and prints the same CoreWLAN value, one line per reading.
JXA = """ObjC.import('Foundation'); ObjC.import('CoreWLAN');
var out = $.NSFileHandle.fileHandleWithStandardOutput;
var client = $.CWWiFiClient.sharedWiFiClient;
while (true) {
  var v = 0;
  try { var i = client.interface; if (!i.isNil()) { v = i.rssiValue; } } catch (e) { v = 0; }
  out.writeData($(String(v) + '\\n').dataUsingEncoding($.NSUTF8StringEncoding));
  delay(%(interval).3f);
}
"""


class OsascriptSource:
    """macOS without pyobjc: one long-running `osascript` (JavaScript for Automation) reads CoreWLAN
    and prints a value every 1/hz s. A thread keeps the last line; read() gives it while it is fresh.
    When osascript exits it is started again, at most every RESTART_S."""

    name = "osascript"
    src = "live"

    def __init__(self, hz: float = RATE_HZ, popen=subprocess.Popen, clock=time.monotonic, which=shutil.which,
                 platform: str = sys.platform):
        if platform != "darwin":
            raise Unsupported("osascript is macOS only")
        if which("osascript") is None:
            raise Unsupported("osascript was not found")
        self.cmd = ["osascript", "-l", "JavaScript", "-e", JXA % {"interval": 1.0 / hz}]
        self.popen, self.clock = popen, clock
        self.proc = None
        self.last = None            # (dbm or None, clock() when it came)
        self.next_try = 0.0
        self.starts = 0
        self.why = None
        self._start()

    def _start(self) -> None:
        now = self.clock()
        if now < self.next_try:
            return
        self.next_try = now + RESTART_S
        try:
            self.proc = self.popen(self.cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, universal_newlines=True, bufsize=1)
        except OSError:
            self.proc = None
            return
        self.starts += 1
        threading.Thread(target=self._pump, args=(self.proc,), daemon=True).start()

    def _pump(self, proc) -> None:
        try:
            for line in proc.stdout:
                self.last = (as_dbm(line.strip()), self.clock())
        except (OSError, ValueError):
            pass

    def read(self) -> int | None:
        if self.proc is None or self.proc.poll() is not None:
            if self.starts >= 2:
                self.why = "osascript keeps exiting (try: pip3 install pyobjc-framework-CoreWLAN)"
            self._start()
        last = self.last
        if last is None or self.clock() - last[1] > FRESH_S:
            return None
        if last[0] is not None:
            self.why = None
        return last[0]

    def close(self) -> None:
        proc, self.proc = self.proc, None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()


PROC_WIRELESS = "/proc/net/wireless"


def proc_level(text: str) -> int | None:
    """The signal level, in dBm, of the first joined interface in /proc/net/wireless:
    "wlan0: 0000   70.  -40.  -256 ..." is interface, status, link quality, level, noise."""
    for line in text.splitlines()[2:]:
        _, sep, rest = line.partition(":")
        cols = rest.split()
        if sep and len(cols) >= 3:
            try:
                quality = float(cols[1].rstrip("."))
            except ValueError:
                continue
            level = as_dbm(cols[2].rstrip("."))
            if quality > 0 and level is not None:
                return level
    return None


class ProcWirelessSource:
    """Linux: the level column of /proc/net/wireless, which the kernel fills in on every read."""

    name = "proc"
    src = "live"

    def __init__(self, path: str = PROC_WIRELESS, platform: str = sys.platform):
        if not platform.startswith("linux"):
            raise Unsupported("/proc/net/wireless is Linux only")
        self.path = path
        try:
            with open(path, encoding="ascii", errors="replace") as f:
                f.read()
        except OSError:
            raise Unsupported(f"this kernel has no {path}") from None

    def read(self) -> int | None:
        try:
            with open(self.path, encoding="ascii", errors="replace") as f:
                return proc_level(f.read())
        except OSError:
            return None

    def close(self) -> None:
        pass


IW_SIGNAL_RE = re.compile(r"^\s*signal:\s*(-?\d+)", re.M)


def wifi_interfaces(root: str = "/sys/class/net") -> list:
    """The names of this machine's Wi-Fi interfaces (used to ask iw; never printed, never sent)."""
    try:
        return sorted(n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n, "wireless"))
                      or os.path.exists(os.path.join(root, n, "phy80211")))
    except OSError:
        return []


class IwLinkSource:
    """Linux without /proc/net/wireless: `iw dev <interface> link`, the "signal:" line. iw prints the
    access point's address in the same text; only the signal is taken from it and nothing is kept."""

    name = "iw"
    src = "live"

    def __init__(self, platform: str = sys.platform, which=shutil.which, interfaces=wifi_interfaces,
                 run=subprocess.run):
        if not platform.startswith("linux"):
            raise Unsupported("iw is Linux only")
        self.iw = which("iw") or next((p for p in ("/usr/sbin/iw", "/sbin/iw") if os.access(p, os.X_OK)), None)
        if self.iw is None:
            raise Unsupported("iw is not installed")
        self.interfaces, self.run = interfaces, run
        if not interfaces():
            raise Unsupported("no Wi-Fi interface was found")

    def read(self) -> int | None:
        for name in self.interfaces():
            try:
                out = self.run([self.iw, "dev", name, "link"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               universal_newlines=True, timeout=0.5).stdout
            except (OSError, subprocess.SubprocessError):
                continue
            m = IW_SIGNAL_RE.search(out or "")
            if m:
                return as_dbm(m.group(1))
        return None

    def close(self) -> None:
        pass


class FakeSource:
    """No radio: readings from a list of (seconds from the start, dBm), each given once when its
    time has come, so what is sent has the list's own rate. loop=True starts the list again."""

    name = "fake"

    def __init__(self, samples, clock=time.monotonic, loop: bool = False, src: str = "sim", span_s: float | None = None):
        self.samples = [(float(t), int(d)) for t, d in samples]
        if not self.samples:
            raise Unsupported("the fake source has no readings")
        self.clock, self.loop, self.src = clock, loop, src
        self.span_s = span_s if span_s is not None else self.samples[-1][0] + 1.0 / FAKE_HZ
        self.start = None
        self.i = 0
        self.given = 0

    @property
    def done(self) -> bool:
        return not self.loop and self.i >= len(self.samples)

    def read(self) -> int | None:
        now = self.clock()
        if self.start is None:
            self.start = now
        if self.i >= len(self.samples):
            if not self.loop:
                return None
            self.start, self.i = self.start + self.span_s, 0
        due = None
        while self.i < len(self.samples) and now - self.start >= self.samples[self.i][0]:
            due = self.samples[self.i][1]   # a late poll takes the newest and lets the older ones go
            self.i += 1
        if due is not None:
            self.given += 1
        return due

    def close(self) -> None:
        pass


def fake_samples(seconds: float, person=(), level: float = FAKE_EMPTY_DBM, drop: float = FAKE_DROP_DB,
                 hz: float = FAKE_HZ, seed: int = 1) -> list:
    """A made-up line shaped like the measured one: whole dBm, `hz` readings a second, one value kept
    for 1 to 2 s, the empty level wobbling by half a dB. person = [(from_s, to_s), ...]: `drop` dB lower."""
    rng = random.Random(seed)
    out, value, until = [], None, 0.0
    for n in range(int(seconds * hz)):
        t = n / hz
        if value is None or t >= until:
            there = any(a <= t < b for a, b in person)
            value = round(rng.gauss(level - (drop if there else 0.0), FAKE_SPREAD_DB))
            until = t + rng.uniform(*FAKE_HOLD_S)
        out.append((round(t, 3), value))
    return out


def file_samples(path) -> list:
    """Readings recorded as "<epoch s> <dBm>" lines, as (seconds from the first line, dBm)."""
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 2:
                try:
                    rows.append((float(parts[0]), int(float(parts[1]))))
                except ValueError:
                    continue
    return [(t - rows[0][0], d) for t, d in rows]


# The sources tried on each system, in order. To add a system: a class with name, src = "live",
# read() -> dBm or None, close(), raising Unsupported from __init__ when it can't run, listed here.
# A source may carry `why`: words for the status line while it has no reading.
SOURCES = {"darwin": (CoreWLANSource, OsascriptSource), "linux": (ProcWirelessSource, IwLinkSource)}
SYSTEM_NAMES = {"darwin": "macOS", "linux": "Linux", "win32": "Windows"}


def pick_source(platform: str = sys.platform, sources=None, only: str | None = None):
    """The first source that starts here. Raises Unsupported, in plain words, when none does."""
    sources = SOURCES if sources is None else sources
    platform = "linux" if platform.startswith("linux") else platform
    system = SYSTEM_NAMES.get(platform, platform)
    if not sources.get(platform):
        can = " and ".join(SYSTEM_NAMES.get(k, k) for k in sources)
        raise Unsupported(f"reading the laptop's Wi-Fi signal is not supported on {system} (only {can}). "
                          "--fake sends a made-up line instead.")
    said = []
    for cls in sources[platform]:
        if only and only != cls.name:
            continue
        try:
            return cls()
        except Unsupported as e:
            said.append(str(e))
    raise Unsupported(f"no way to read the Wi-Fi signal on this {system}: "
                      + "; ".join(said or [f"--source {only} is not for {system}"]))


# ---------------------------------------------------------------------------
# The hotspot check, the pings, the status line and the loop
# ---------------------------------------------------------------------------

def local_address(host: str, port: int) -> str | None:
    """The address this machine would send to host from. Nothing is sent (a UDP socket only picks its route)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((host, port))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def on_net(address: str | None, net: str | None) -> bool:
    """True when the check is off (net None), or the address lies in net."""
    if net is None:
        return True
    try:
        return address is not None and ipaddress.ip_address(address) in ipaddress.ip_network(net)
    except ValueError:
        return False


def ping_command(host: str, hz: float, platform: str = sys.platform) -> list | None:
    """The system ping that runs until stopped, or None where there is none to use. The shortest wait
    a ping allows without root: 0.1 s on macOS, 0.2 s on every Linux."""
    if hz <= 0:
        return None
    if platform == "darwin":
        return ["ping", "-n", "-q", "-i", f"{max(0.1, 1.0 / hz):.3f}", host]
    if platform.startswith("linux"):
        return ["ping", "-n", "-q", "-i", f"{max(0.2, 1.0 / hz):.3f}", host]
    return None


class Pinger:
    """Keeps a ping to the board running while the laptop is on the hotspot, and stops it when it is
    not. It never stops the reader: a ping that can't run is said once and the readings carry on."""

    def __init__(self, host: str, hz: float = PING_HZ, platform: str = sys.platform, popen=subprocess.Popen,
                 clock=time.monotonic, say=log):
        self.host, self.popen, self.clock, self.say = host, popen, clock, say
        self.cmd = ping_command(host, hz, platform)
        self.proc = None
        self.next_try = 0.0

    def check(self, joined: bool = True) -> None:
        if self.cmd is None:
            return
        if not joined:
            self.stop()
            return
        if (self.proc is None or self.proc.poll() is not None) and self.clock() >= self.next_try:
            self.next_try = self.clock() + RESTART_S
            try:
                self.proc = self.popen(self.cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
            except OSError as e:
                self.cmd = None
                self.say(f"no pings to {self.host} ({e.strerror or type(e).__name__}): the readings carry on without them")

    def stop(self) -> None:
        proc, self.proc = self.proc, None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()


class Status:
    """One line every `every_s`: the rate and the last dBm, or why nothing is being sent."""

    def __init__(self, target: str, link_id: str = LINK_ID, every_s: float = STATUS_S, clock=time.monotonic, say=log):
        self.target, self.link_id, self.every_s, self.clock, self.say = target, link_id, every_s, clock, say
        self.since = clock()
        self.n = self.failed = 0
        self.last = None
        self.error = None

    def sent(self, dbm: int) -> None:
        self.n, self.last = self.n + 1, dbm

    def not_sent(self, error) -> None:
        self.failed, self.error = self.failed + 1, error

    def tick(self, joined: bool, dry: bool = False, why: str | None = None) -> None:
        now = self.clock()
        span = now - self.since
        if span < self.every_s - 1e-3:   # a poll that lands a hair early still counts as the second
            return
        if not joined:
            self.say("waiting: this laptop is not on the sensing hotspot (no 10.42.0.x address), nothing is sent; "
                     "join it, or --net any")
        elif self.n == 0 and not self.failed:
            self.say(f"no reading: {why or 'Wi-Fi is off or not joined'}; still trying")
        else:
            words = f"{self.n / span:.1f}/s  {self.last if self.last is not None else '__'} dBm  {self.link_id} "
            words += "(dry: nothing sent)" if dry else f"-> {self.target}"
            if self.failed:
                words += f"  {self.failed} not sent ({self.error})"
            self.say(words)
        self.since, self.n, self.failed, self.error = now, 0, 0, None


def run(source, send, hz: float = RATE_HZ, seconds: float = 0, stop=lambda: False, joined=lambda: True,
        status: Status | None = None, dry: bool = False, tick=None, clock=time.monotonic, sleep=time.sleep) -> list:
    """Poll `source` hz times a second until `seconds` pass (0 = for ever) or stop(). Every reading
    goes to send(dbm) while joined() says the laptop is on the hotspot. tick(joined) runs once a
    second (the pings). Returns the dBm values sent."""
    interval = 1.0 / hz
    start = clock()
    end = start + seconds if seconds else None
    next_poll, next_check, is_joined = start, start, True
    values = []
    while not stop() and (end is None or clock() < end):
        now = clock()
        if now >= next_check:               # once a second: is this still the hotspot?
            is_joined, next_check = bool(joined()), now + 1.0
            if tick is not None:
                tick(is_joined)
        dbm = source.read()
        if dbm is not None and is_joined:
            try:
                send(dbm)
            except OSError as e:
                if status:
                    status.not_sent(e.strerror or type(e).__name__)
            else:
                values.append(dbm)
                if status:
                    status.sent(dbm)
        if status:
            status.tick(is_joined, dry, getattr(source, "why", None))
        next_poll += interval
        wait = next_poll - clock()
        if wait > 0:
            sleep(wait)
        else:
            next_poll = clock()             # fell behind: don't spin to catch up
    return values


def summary(values: list, seconds: float, link_id: str = LINK_ID) -> str:
    if not values:
        return f"{link_id}: no readings in {seconds:.1f} s"
    return (f"{link_id}: {len(values)} readings in {seconds:.1f} s = {len(values) / seconds:.1f}/s, "
            f"median {statistics.median(values):g} dBm")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_bus(text: str) -> tuple:
    host, _, port = text.rpartition(":")
    if not host:
        return text, BUS_PORT
    return host, int(port)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="This laptop's own Wi-Fi signal reading, sent as pi5><node>:wifi")
    ap.add_argument("--node", default=NODE, help="which laptop this is, as the layout file names it (default laptop1)")
    ap.add_argument("--bus", default=f"{os.environ.get('BUS_HOST') or BUS_HOST}:{os.environ.get('BUS_PORT') or BUS_PORT}",
                    help="the board's bus, host:port (default 192.168.77.2:5600)")
    ap.add_argument("--hz", type=float, default=RATE_HZ, help="polls a second (default 10)")
    ap.add_argument("--ping-hz", type=float, default=PING_HZ, help="pings to the board a second (default 10; 0 = none)")
    ap.add_argument("--seconds", type=float, default=0, help="stop after this long and print a summary")
    ap.add_argument("--net", default=HOTSPOT_NET,
                    help="send only while this laptop has an address in this network (default 10.42.0.0/24); 'any' = always")
    ap.add_argument("--source", choices=("auto", "pyobjc", "osascript", "proc", "iw"), default="auto",
                    help="which way to read (default: the first that works on this system)")
    ap.add_argument("--dry", action="store_true", help="read and print the status line, send nothing, no pings")
    ap.add_argument("--fake", action="store_true", help='no radio: a made-up line, 10 s empty then 10 s person, src "sim"')
    ap.add_argument("--fake-file", metavar="PATH", help='no radio: replay "<epoch s> <dBm>" lines, src "replay"')
    args = ap.parse_args(argv)

    try:
        host, port = parse_bus(args.bus)
        link_id = link_for(args.node)
        net = None if args.net == "any" else str(ipaddress.ip_network(args.net))
        if args.hz <= 0 or args.ping_hz < 0:
            raise ValueError("--hz is over 0, and --ping-hz is 0 or more")
    except ValueError as e:
        print(f"laptop_line: {e}", file=sys.stderr)
        return 2

    try:
        if args.fake_file:
            source = FakeSource(file_samples(args.fake_file), loop=True, src="replay")
        elif args.fake:
            source = FakeSource(fake_samples(20, person=[(10, 20)]), loop=True, span_s=20.0)
        else:
            source = pick_source(only=None if args.source == "auto" else args.source)
        if args.fake or args.fake_file:
            net = None
            args.hz = max(args.hz, 50.0)   # a fake gives each reading once, when it is due: look often
            args.ping_hz = 0
    except (Unsupported, OSError) as e:
        print(f"laptop_line: {e}", file=sys.stderr)
        return 2

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)   # one socket, one seq counter
    seq = 0

    def send(dbm: int) -> None:
        nonlocal seq
        data = make_message(dbm, seq, link_id, source.src)
        seq += 1
        if not args.dry:
            sock.sendto(data, (host, port))

    def stop_now(*_):
        raise KeyboardInterrupt

    try:
        signal.signal(signal.SIGTERM, stop_now)
    except (ValueError, OSError):
        pass
    pinger = Pinger(host, 0 if args.dry else args.ping_hz)
    log(f"reading with {source.name}, {args.hz:g} times a second -> {host}:{port} as {link_id}"
        + ("" if net is None else f"; only while on {net}")
        + (f"; pinging {host}" if pinger.cmd else "") + ". Ctrl-C stops it.")
    started = time.monotonic()
    values = []
    try:
        values = run(source, send, args.hz, args.seconds, joined=lambda: on_net(local_address(host, port), net),
                     status=Status(f"{host}:{port}", link_id), dry=args.dry, tick=pinger.check)
    except KeyboardInterrupt:
        log("stopped")
    finally:
        pinger.stop()
        source.close()
        sock.close()
    if args.seconds:
        print(summary(values, max(time.monotonic() - started, 1e-3), link_id))
    return 0


if __name__ == "__main__":
    sys.exit(main())
