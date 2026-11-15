"""Pi radio node.

Runs on the Raspberry Pi 5 as root (CONTRACTS.md §9).

Advertises its own beacon (manufacturer data FFFF 52 53 'S' for pi5, from radio/nodes.json) every
20 ms, and scans with duplicate filtering OFF for the other beacons.  Forwards kept readings
to the board bus at 192.168.77.2:5600 as contract-v2 rssi messages.

What it does follows from the Bluetooth links in radio/nodes.json: a node that is the tx of no
link doesn't advertise (listen-only), and a node that is the rx of no link doesn't scan and sends
nothing (beacon-only: no network needed at all). RADIO_ROLE or --beacon-only / --listen-only set it
by hand instead.

Advertising: for each legacy advertising type, in this order: connectable undirected (ADV_IND),
scannable (ADV_SCAN_IND), non-connectable (ADV_NONCONN_IND), it walks the intervals 20, 30, 40, 50,
60, 80, 100 ms and stops at the first one the controller accepts. It keeps the fastest of them (an
earlier type wins a tie), always with the same manufacturer data, and all three are heard by a
passive scan. ADV_MODE or --adv tries one type only. It logs one line with what it kept and what was
refused ("advertising every 30 ms, connectable (ADV_IND); refused: connectable 20 ms"), and once at
start what the controller says it can do (HCI version, extended advertising commands, LE features).
"Accepted" is the controller's Success to LE Set Advertising Parameters and then to Advertising
Enable: legacy HCI has no command that reads the interval back, so the receivers' rate is the check.
Connectable advertising offers nothing: anything that connects is dropped at once, and the
beacon starts again. The node never pairs and never serves anything.

Matching is by advertised manufacturer data, never by MAC address.
No MACs, BSSIDs or local secrets are stored here.

It keeps going when things around it fail:
- no Ethernet link yet, or the board isn't listening: readings that can't be sent
  are dropped and counted, and the beacon keeps advertising;
- something else resets or reconfigures the controller (bluetoothd powering it on,
  an HCI Reset, another program's scan): advertising and scanning are set up again;
- the controller goes away (powered off, unplugged): it exits non-zero and systemd
  starts it again (board/units/radio-sight-radio-node.service).
Every 10 s it prints one status line (journalctl -u radio-sight-radio-node).

Environment variables (set in .env at repo root, gitignored):
    RADIO_NODE   which Pi this is, a node id from nodes.json that is a beacon and a receiver (default pi5)
    HCI_IFACE    HCI device index (default 0  → hci0)
    BUS_HOST     bus UDP host (default 192.168.77.2)
    BUS_PORT     bus UDP port (default 5600)
    RADIO_ROLE   auto (default: from the links), both, beacon-only or listen-only
    ADV_MODE     auto (default: the three types above), connectable, scannable or non-connectable

Entry point:
    sudo python -m pi.radio_node
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import statistics
import struct
import sys
import time

from radio import hci
from radio.hci_scan import BeaconScanner, kept, make_bus_emitter, open_controller
from radio.nodes import BEACONS, DOC, LINKS

HCI_IDX: int = int(os.environ.get("HCI_IFACE", "0").strip().removeprefix("hci") or "0")  # "0" or "hci0"
BUS_HOST: str = os.environ.get("BUS_HOST", "192.168.77.2")
BUS_PORT: int = int(os.environ.get("BUS_PORT", "5600"))

# The Pis that both advertise and listen (nodes.json roles). Each runs this node with its own id:
# --node, or RADIO_NODE in .env, else pi5.
RADIO_NODES = [n["id"] for n in DOC["nodes"] if {"beacon", "receiver"} <= set(n.get("roles", []))]
RX = os.environ.get("RADIO_NODE", "pi5")
RADIO_ROLE = os.environ.get("RADIO_ROLE", "auto").strip() or "auto"
ADV_MODE = os.environ.get("ADV_MODE", "auto").strip() or "auto"
ROLES = ("auto", "both", "beacon-only", "listen-only")
ADV_MODES = ("auto", "connectable", "scannable", "non-connectable")


def beacon_payload(node: str) -> bytes:
    """The node's manufacturer data from nodes.json, company id first: FFFF 52 53 <letter>."""
    return next(payload for payload, who in BEACONS.items() if who == node)


def beacon_letter(node: str) -> str:
    return chr(beacon_payload(node)[-1])


def heard_by(node: str) -> tuple:
    """The Bluetooth links whose receiver is `node`, in nodes.json order."""
    return tuple(link for link, e in LINKS.items() if e["rx"] == node and e["kind"] == "ble")


def link_roles(node: str, links=None) -> tuple:
    """(advertise, scan) from the Bluetooth links: advertise if `node` is the tx of one, scan if it is the rx of one.

    Only the core links count: every receiver hears the hall beacons, so they would make every node scan.
    """
    ble = [e for e in (LINKS if links is None else links).values() if e["kind"] == "ble"]
    return any(e["tx"] == node for e in ble), any(e["rx"] == node for e in ble)


def roles(node: str, role: str = "auto", links=None) -> tuple:
    """(advertise, scan) for `role`; auto takes them from the links in nodes.json."""
    if role == "both":
        return True, True
    if role == "beacon-only":
        return True, False
    if role == "listen-only":
        return False, True
    return link_roles(node, links)


# 20 ms interval in 0.625 ms units: 20 / 0.625 = 32 = 0x0020
ADV_INTERVAL_HCI: int = 32
# Core 4.x made 100 ms (0x00A0) the floor for scannable and non-connectable adverts; 5.0 dropped it.
# A controller that still applies it answers 0x12 (Invalid HCI Command Parameters), as Pi B's does.
ADV_INTERVAL_4X_MIN: int = 0x00A0
INVALID_PARAMS = 0x12
REFUSED = {0x11, INVALID_PARAMS}   # Unsupported Feature or Parameter Value, Invalid HCI Command Parameters
LADDER_MS = (20, 30, 40, 50, 60, 80, 100)
TYPE_ORDER = ("connectable", "scannable", "non-connectable")
ADV_IND, ADV_SCAN_IND, ADV_NONCONN_IND = 0x00, 0x02, 0x03
ADV_TYPE = {"non-connectable": ADV_NONCONN_IND, "scannable": ADV_SCAN_IND, "connectable": ADV_IND}
ADV_NAME = {"non-connectable": "ADV_NONCONN_IND", "scannable": "ADV_SCAN_IND", "connectable": "ADV_IND"}

HCI_RESET = 0x0C03
HCI_DISCONNECT = 0x0406
READ_LOCAL_VERSION = 0x1001
LE_READ_LOCAL_FEATURES = 0x2003
LE_SET_ADV_PARAMS = 0x2006
LE_SET_ADV_DATA = 0x2008
LE_SET_ADV_ENABLE = 0x200A
LE_SET_EXT_ADV_ENABLE = 0x2039
EXT_ADV_PARAMS_BIT = (36, 1)   # Supported_Commands: LE Set Extended Advertising Parameters
LE_FEATURE_EXT_ADV = 12        # LE Features: LE Extended Advertising

# Something connecting to the connectable beacon: LE (Enhanced) Connection Complete with this
# controller as the peripheral. It is dropped at once (reason 0x13) and the beacon starts again.
EV_DISCONN_COMPLETE = 0x05
LE_CONN_COMPLETE = (0x01, 0x0A, 0x29)
ROLE_PERIPHERAL = 0x01
REMOTE_USER_ENDED = 0x13
REARM_WAIT_S = 2.0  # a controller that won't advertise while connected: wait this long at most for the drop

# A Command Complete for one of these that this node didn't send means something else
# changed the controller's advertising or scanning, so ours is set up again.
WATCHED = {
    HCI_RESET, LE_SET_ADV_PARAMS, LE_SET_ADV_DATA, LE_SET_ADV_ENABLE, LE_SET_EXT_ADV_ENABLE,
    hci.LE_SET_SCAN_PARAMS, hci.LE_SET_SCAN_ENABLE, hci.LE_SET_EXT_SCAN_PARAMS, hci.LE_SET_EXT_SCAN_ENABLE,
}
SETTLE_S = 1.0    # wait this long after the last outside change before setting up again
QUIET_S = 5.0     # no advert from anything for this long: the scan was stopped, set up again
STATUS_S = 10.0   # one status line this often


def interval_ms(interval: int) -> float:
    """An advertising interval in 0.625 ms units, in ms."""
    return interval * 0.625


def units(ms: int) -> int:
    """An interval in ms, in 0.625 ms units: 20 -> 32, 30 -> 48, 100 -> 160."""
    return round(ms / 0.625)


class Advert:
    """How the controller took the beacon: kind (connectable, scannable, non-connectable) and interval (0.625 ms units)."""

    def __init__(self, kind: str, interval: int):
        self.kind, self.interval = kind, interval

    @property
    def connectable(self) -> bool:
        return self.kind == "connectable"

    def __eq__(self, other):
        return isinstance(other, Advert) and (self.kind, self.interval) == (other.kind, other.interval)

    def __repr__(self):
        return f"Advert({self.kind!r}, {self.interval})"

    def __str__(self):
        """For the status line: "every 20 ms" (non-connectable), or "every 30 ms, connectable"."""
        return f"every {interval_ms(self.interval):g} ms" + ("" if self.kind == "non-connectable" else f", {self.kind}")


def build_adv_params_params(interval: int = ADV_INTERVAL_HCI, kind: str = "non-connectable") -> bytes:
    """15 parameter bytes for LE Set Advertising Parameters (20 ms, non-connectable undirected by default)."""
    p = bytearray(15)
    struct.pack_into("<H", p, 0, interval)
    struct.pack_into("<H", p, 2, interval)
    p[4] = ADV_TYPE[kind]   # 0x00 ADV_IND, 0x02 ADV_SCAN_IND or 0x03 ADV_NONCONN_IND
    p[5] = 0x00   # own address: public
    p[6] = 0x00   # peer address: public
    # bytes 7-12: peer address zeros
    p[13] = 0x07  # channel map: 37, 38, 39
    p[14] = 0x00  # filter policy: process all
    return bytes(p)


def build_adv_params_cmd(interval: int = ADV_INTERVAL_HCI, kind: str = "non-connectable") -> bytes:
    return hci.command_packet(LE_SET_ADV_PARAMS, build_adv_params_params(interval, kind))


def build_adv_data_params(node: str = RX) -> bytes:
    """32 parameter bytes: length of significant data (7) + 31 padded data bytes."""
    payload = beacon_payload(node)
    adv = bytes([len(payload) + 1, 0xFF]) + payload
    return bytes([len(adv)]) + adv + bytes(31 - len(adv))


def build_adv_data_cmd(node: str = RX) -> bytes:
    return hci.command_packet(LE_SET_ADV_DATA, build_adv_data_params(node))


def build_adv_enable_cmd(enable: bool) -> bytes:
    return hci.command_packet(LE_SET_ADV_ENABLE, bytes([0x01 if enable else 0x00]))


def hci_version(dev: hci.Hci):
    """The controller's HCI_Version (9 = Bluetooth 5.0), or None if it doesn't say."""
    try:
        result = dev.command(READ_LOCAL_VERSION, check=False)
    except hci.HciError:
        return None
    return result[1] if len(result) >= 2 and result[0] == 0 else None


def capabilities(dev: hci.Hci) -> str:
    """One log line, read once at start, on what the controller says it can do: its HCI version, whether
    it has the extended advertising and scanning commands and the LE Extended Advertising feature, and
    the raw LE feature bytes. Nothing is chosen from it: the node uses the legacy commands only."""
    version = hci_version(dev)
    try:
        commands = dev.command(hci.READ_LOCAL_SUPPORTED_COMMANDS, check=False)[1:65]
        features = dev.command(LE_READ_LOCAL_FEATURES, check=False)
    except hci.HciError:
        commands, features = b"", b""
    words = [f"HCI version {version if version is not None else '__'}",
             f"extended advertising commands {'yes' if hci.supports(commands, EXT_ADV_PARAMS_BIT) else 'no'}",
             f"extended scanning commands {'yes' if hci.supports(commands, hci.EXT_SCAN_ENABLE_BIT) else 'no'}"]
    if len(features) >= 9 and features[0] == 0:
        bits = int.from_bytes(features[1:9], "little")
        words += [f"LE extended advertising feature {'yes' if bits >> LE_FEATURE_EXT_ADV & 1 else 'no'}",
                  f"LE features {features[1:9].hex()}"]
    else:
        words.append("LE features __")
    return "[pi.radio_node] controller: " + ", ".join(words)


def try_params(dev: hci.Hci, advert: Advert) -> bool:
    """LE Set Advertising Parameters with `advert`. False if the controller refuses those values."""
    try:
        dev.command(LE_SET_ADV_PARAMS, build_adv_params_params(advert.interval, advert.kind))
        return True
    except hci.HciError as e:
        if e.status in REFUSED:
            return False
        raise


def ladder(dev: hci.Hci, kinds=TYPE_ORDER):
    """For each kind in order, the intervals in LADDER_MS from the fastest until the controller accepts one.

    A kind's walk stops where it can't beat the best so far (an earlier kind wins a tie). Returns the
    fastest accepted Advert (None if all were refused) and the refused ones. If anything was sent after
    the one returned, even a refused command, its parameters are sent again, so the controller holds them.
    """
    best, last, refused = None, None, []
    for kind in kinds:
        for ms in LADDER_MS:
            advert = Advert(kind, units(ms))
            if best is not None and advert.interval >= best.interval:
                break
            last = advert
            if try_params(dev, advert):
                best = advert
                break
            refused.append(advert)
    if best is not None and last != best and not try_params(dev, best):
        raise hci.HciError(LE_SET_ADV_PARAMS, text=f"{best.kind} every {interval_ms(best.interval):g} ms "
                                                   "was accepted, then refused")
    return best, refused


def refused_words(refused) -> str:
    """'connectable 20 ms; scannable 20, 30 ms', or 'nothing'."""
    by_kind: dict = {}
    for advert in refused:
        by_kind.setdefault(advert.kind, []).append(f"{interval_ms(advert.interval):g}")
    return "; ".join(f"{kind} {', '.join(ms)} ms" for kind, ms in by_kind.items()) or "nothing"


def kept_line(node: str, advert: Advert, refused) -> str:
    """The one line saying what was kept and what was refused."""
    line = (f"[pi.radio_node] beacon {beacon_letter(node)}: advertising every {interval_ms(advert.interval):g} ms, "
            f"{advert.kind} ({ADV_NAME[advert.kind]}); refused: {refused_words(refused)}")
    if advert.connectable:
        line += "; anything that connects is dropped at once"
    return line


def start_advertising(dev: hci.Hci, node: str = RX, mode: str = "auto", known=None, log=lambda line: None) -> Advert:
    """Advertise this node's beacon at the fastest interval the controller takes. Returns that Advert.

    With `known` (what it took last time) that is tried first, and the ladder is walked only if it is
    refused now. mode is auto (every type) or one type; if that type is refused at every interval, the
    others are walked too.
    """
    dev.command(LE_SET_ADV_ENABLE, bytes([0x00]), check=False)
    if known is None or not try_params(dev, known):
        kinds = TYPE_ORDER if mode == "auto" else (mode,)
        advert, refused = ladder(dev, kinds)
        if advert is None and mode != "auto":
            advert, more = ladder(dev, [k for k in TYPE_ORDER if k != mode])
            refused += more
        if advert is None:
            raise hci.HciError(LE_SET_ADV_PARAMS, text="every advertising type was refused at every interval "
                                                       f"from {LADDER_MS[0]} to {LADDER_MS[-1]} ms")
        log(kept_line(node, advert, refused))
        known = advert
    dev.command(LE_SET_ADV_DATA, build_adv_data_params(node))
    dev.command(LE_SET_ADV_ENABLE, bytes([0x01]))
    return known


def stop_advertising(dev: hci.Hci) -> None:
    dev.command(LE_SET_ADV_ENABLE, bytes([0x00]), check=False)


def completed_opcode(packet: bytes):
    """The opcode a Command Complete event answers, or None for any other packet."""
    if len(packet) >= 6 and packet[0] == hci.EVENT_PKT and packet[1] == hci.EV_CMD_COMPLETE:
        return struct.unpack_from("<H", packet, 4)[0]
    return None


def is_advert(packet: bytes) -> bool:
    """True for an LE (Extended) Advertising Report from any advertiser, ours or not."""
    return (len(packet) >= 4 and packet[0] == hci.EVENT_PKT and packet[1] == hci.EV_LE_META
            and packet[3] in (hci.LE_ADV_REPORT, hci.LE_EXT_ADV_REPORT))


def peripheral_connection(packet: bytes):
    """The handle of a new connection made to this controller's advert (it is the peripheral), else None.

    A connection this controller made itself (central) belongs to something else and is left alone.
    The peer's address in the event is never read.
    """
    if (len(packet) >= 8 and packet[0] == hci.EVENT_PKT and packet[1] == hci.EV_LE_META
            and packet[3] in LE_CONN_COMPLETE and packet[4] == 0x00 and packet[7] == ROLE_PERIPHERAL):
        return struct.unpack_from("<H", packet, 5)[0] & 0x0FFF
    return None


def disconnected(packet: bytes):
    """The handle a Disconnection Complete event ends, else None."""
    if len(packet) >= 7 and packet[0] == hci.EVENT_PKT and packet[1] == EV_DISCONN_COMPLETE:
        return struct.unpack_from("<H", packet, 4)[0] & 0x0FFF
    return None


def drop(dev: hci.Hci, handle: int) -> bool:
    """Ends a connection to the beacon and advertises again. False if the controller won't until it's gone."""
    dev.command(HCI_DISCONNECT, struct.pack("<HB", handle, REMOTE_USER_ENDED), check=False)
    return dev.command(LE_SET_ADV_ENABLE, bytes([0x01]), check=False)[:1] == b"\x00"


def hear_disconnects(dev: hci.Hci) -> None:
    """Adds Disconnection Complete to the socket's event filter (Hci.open lets only three events in)."""
    setsockopt = getattr(dev.sock, "setsockopt", None)
    if setsockopt is not None:
        setsockopt(hci.SOL_HCI, hci.HCI_FILTER, hci.event_filter(
            hci.EV_CMD_COMPLETE, hci.EV_CMD_STATUS, hci.EV_LE_META, EV_DISCONN_COMPLETE))


class BusSender:
    """emit(link, dbm) to the bus that never raises: a reading that can't be sent is dropped and counted.

    With no Ethernet link yet, sendto fails (network unreachable); the node keeps advertising
    and scanning, and the readings flow again as soon as the link is up.
    """

    def __init__(self, sock: socket.socket, target: tuple, rx: str = RX):
        self._emit = make_bus_emitter(sock, target, rx=rx)
        self.sent = self.failed = 0
        self.error = None

    def __call__(self, link: str, dbm: int) -> None:
        try:
            self._emit(link, dbm)
            self.sent += 1
        except OSError as e:
            self.failed += 1
            self.error = e


def set_up(dev: hci.Hci, scanner: BeaconScanner, known=None, scan: bool = True, advertise: bool = True,
           log=lambda line: None, mode: str = "auto"):
    """Advertise this node's beacon and scan, from whatever state the controller is in. Returns the Advert.

    Both turn themselves off first, because their parameters can't change while they're on.
    With scan False only the beacon is set up (beacon-only); with advertise False only the scan
    (listen-only), and this node's beacon is turned off, so it returns None.
    """
    if advertise:
        advert = start_advertising(dev, scanner.rx, mode, known, log)
    else:
        stop_advertising(dev)
        advert = None
    if scan:
        scanner.start()
    else:
        scanner.stop()
    return advert


PI_LINKS = heard_by("pi5")


def beacon_words(node: str, advert) -> str:
    """'beacon S every 20 ms' (with ', connectable' when it is), or 'not advertising'."""
    return f"beacon {beacon_letter(node)} {advert}" if advert is not None else "not advertising"


def status_line(counts: dict, seconds: float, bus: BusSender, redone: int, links=PI_LINKS,
                beacon=None) -> str:
    """Rates and sends since the last status line; how often the controller was set up again since start;
    and, if given, the beacon this node advertises and the interval the controller took (e.g. "beacon S every 20 ms")."""
    rates = ", ".join(f"{link} {counts.get(link, 0) / seconds:.1f}/s" for link in links)
    line = f"[pi.radio_node] {rates}; sent {bus.sent}, not sent {bus.failed}"
    if bus.failed and bus.error is not None:
        line += f" ({bus.error.strerror or bus.error})"
    bus.sent = bus.failed = 0
    bus.error = None
    line += f"; set up again {redone}x since start"
    return line + (f"; {beacon}" if beacon else "")


def summary(seen: dict, windows: dict, seconds: float, links=PI_LINKS) -> str:
    """One line per Pi link for the Gate 2 table: readings, adverts/s over the run, the lowest and
    median 10 s rate (a beacon that slows down or drops out shows up here), and the median dBm."""
    lines = [f"{'link':<14} {'n':>6} {'adverts/s':>10} {'lowest 10s':>11} {'median 10s':>11} {'median dBm':>11}"]
    for link in links:
        values, rates = seen.get(link, []), windows.get(link, [])
        low = f"{min(rates):.1f}" if rates else "__"
        mid = f"{statistics.median(rates):.1f}" if rates else "__"
        dbm = f"{statistics.median(values):.1f}" if values else "__"
        lines.append(f"{link:<14} {len(values):>6} {len(values) / seconds:>10.1f} {low:>11} {mid:>11} {dbm:>11}")
    return "\n".join(lines)


def run(dev: hci.Hci, bus_host: str = BUS_HOST, bus_port: int = BUS_PORT,
        seconds: float = 0, stop=lambda: False, seen=None, windows=None, bus_sock=None,
        clock=time.monotonic, log=lambda line: print(line, file=sys.stderr, flush=True), node: str = RX,
        scan: bool = True, advertise: bool = True, adv_mode: str = ADV_MODE):
    """Advertise `node`'s beacon and scan for the beacons it hears, forwarding rssi to the board bus.

    If given, `seen` is filled with {link: [dbm, ...]} and returned (the service passes none, so
    nothing piles up). If given, `windows` gets each Pi link's rate for every 10 s status line.
    An OSError from the HCI socket (the controller is down or gone) is raised
    to the caller; one from the bus socket never is.

    With scan False the node only advertises (beacon-only): nothing is heard or sent, no bus socket
    is opened, and silence is not a reason to set up again. With advertise False it only listens.
    """
    if not (scan or advertise):
        raise ValueError(f"{node} neither advertises nor scans: nothing to do")
    own_sock = scan and bus_sock is None
    bus_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) if own_sock else bus_sock
    bus = BusSender(bus_sock, (bus_host, bus_port), rx=node) if scan else None
    links = heard_by(node) if scan else ()
    scanner = None
    end = clock() + seconds if seconds else None
    try:
        scanner = BeaconScanner(dev, rx=node)
        # The Pi advertises with the legacy commands, so its scan stays legacy too: the two
        # command families must not be mixed on one controller.
        scanner.ext = False
        scanner.mode = "legacy"
        if advertise:
            log(capabilities(dev))
        advert = set_up(dev, scanner, None, scan, advertise, log, adv_mode)
        now = clock()
        last_advert = last_status = now
        redo_at = None
        redone = dropped = 0
        waiting = wait_until = None   # a dropped connection the controller must end before it advertises again
        quiet_told = False  # say "no adverts" once per quiet spell, not every QUIET_S
        counts: dict = {}
        while not stop() and (end is None or clock() < end):
            packet = dev.recv(0.5)
            now = clock()
            if packet:
                handle = peripheral_connection(packet) if advert is not None and advert.connectable else None
                if is_advert(packet):
                    last_advert, quiet_told = now, False
                    if scan:
                        for link, dbm in kept(packet, node):
                            bus(link, dbm)
                            if seen is not None:
                                seen.setdefault(link, []).append(dbm)
                            counts[link] = counts.get(link, 0) + 1
                elif handle is not None:
                    dropped += 1
                    log(f"[pi.radio_node] something connected to beacon {beacon_letter(node)}; "
                        "dropped it and advertising again")
                    if not drop(dev, handle):
                        waiting, wait_until = handle, now + REARM_WAIT_S
                elif waiting is not None and disconnected(packet) == waiting:
                    waiting, redo_at = None, now
                elif completed_opcode(packet) in WATCHED:
                    if redo_at is None:
                        log(f"[pi.radio_node] something else sent HCI command 0x{completed_opcode(packet):04X}; "
                            "setting up advertising and scanning again")
                    redo_at = now + SETTLE_S
            if waiting is not None and now >= wait_until:
                waiting, redo_at = None, now
            if scan and redo_at is None and now - last_advert >= QUIET_S:
                if not quiet_told:
                    log(f"[pi.radio_node] no adverts for {QUIET_S:.0f} s; setting up advertising and scanning "
                        f"again every {QUIET_S:.0f} s until one arrives")
                    quiet_told = True
                redo_at = now
            if redo_at is not None and now >= redo_at and waiting is None:
                advert = set_up(dev, scanner, advert, scan, advertise, log, adv_mode)
                redone += 1
                redo_at = None
                last_advert = clock()
            if now - last_status >= STATUS_S:
                if windows is not None:
                    for link in links:
                        windows.setdefault(link, []).append(counts.get(link, 0) / (now - last_status))
                beacon = beacon_words(node, advert) + ("" if scan else ", not scanning")
                if dropped:
                    beacon += f", {dropped} connection{'s' if dropped != 1 else ''} dropped since start"
                if scan:
                    log(status_line(counts, now - last_status, bus, redone, links, beacon))
                else:
                    log(f"[pi.radio_node] beacon only, nothing sent; set up again {redone}x since start; {beacon}")
                counts, last_status = {}, now
        return seen
    finally:
        try:
            if scanner is not None:
                scanner.stop()
            stop_advertising(dev)
        except (OSError, hci.HciError):
            pass  # the controller is already down or gone; nothing left to turn off
        if own_sock:
            bus_sock.close()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dev", type=int, default=HCI_IDX, help="HCI device number (default: 0)")
    ap.add_argument("--seconds", type=float, default=0,
                    help="stop after this long and print a Gate 2 summary (0 = run until stopped)")
    ap.add_argument("--node", choices=RADIO_NODES, default=RX,
                    help="which Pi this is (default: RADIO_NODE from .env, else pi5)")
    role = ap.add_mutually_exclusive_group()
    role.add_argument("--role", choices=ROLES, default=RADIO_ROLE,
                      help="auto: from the links in nodes.json (default: RADIO_ROLE from .env, else auto)")
    role.add_argument("--beacon-only", dest="role", action="store_const", const="beacon-only",
                      help="advertise the beacon and nothing else: no scan, nothing sent, no network needed")
    role.add_argument("--no-scan", dest="role", action="store_const", const="beacon-only",
                      help="the same as --beacon-only")
    role.add_argument("--listen-only", dest="role", action="store_const", const="listen-only",
                      help="scan and send readings, without advertising this Pi's beacon")
    ap.add_argument("--adv", choices=ADV_MODES, default=ADV_MODE,
                    help="auto: the fastest of connectable, scannable and non-connectable, 20 to 100 ms "
                         "(default: ADV_MODE from .env, else auto)")
    args = ap.parse_args(argv)
    if args.role not in ROLES:
        ap.error(f"RADIO_ROLE is one of {', '.join(ROLES)}, not {args.role!r}")
    if args.adv not in ADV_MODES:
        ap.error(f"ADV_MODE is one of {', '.join(ADV_MODES)}, not {args.adv!r}")
    advertise, scan = roles(args.node, args.role)
    if not (advertise or scan):
        sys.exit(f"{args.node} is the tx and the rx of no Bluetooth link in nodes.json: nothing to do "
                 "(RADIO_ROLE=both in .env runs it anyway)")
    # Only a timed run keeps readings, for its summary; the service keeps nothing.
    seen, windows = ({}, {}) if args.seconds else (None, None)

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    dev = open_controller(args.dev)
    hear_disconnects(dev)

    why = "from the links in nodes.json" if args.role == "auto" else args.role
    print(
        f"[pi.radio_node] {args.node}: "
        + (f"advertising beacon {beacon_letter(args.node)}" if advertise else "not advertising")
        + (", scanning" if scan else ", not scanning") + f" on hci{args.dev} ({why}); "
        + (f"forwarding to {BUS_HOST}:{BUS_PORT}" if scan else "sending nothing, no network needed"),
        file=sys.stderr, flush=True,
    )
    started = time.monotonic()
    try:
        run(dev, bus_host=BUS_HOST, bus_port=BUS_PORT, seconds=args.seconds, seen=seen, windows=windows,
            node=args.node, scan=scan, advertise=advertise, adv_mode=args.adv)
    except KeyboardInterrupt:
        pass
    except hci.HciError as e:
        sys.exit(f"hci{args.dev}: {e}")
    except OSError as e:
        # Powered off, rfkill'd or gone: exit non-zero so systemd starts the node again.
        sys.exit(f"hci{args.dev}: {e}. Is Bluetooth on? sudo rfkill unblock bluetooth; sudo bluetoothctl power on")
    finally:
        dev.close()
        if seen is not None and scan:
            print(summary(seen, windows, max(time.monotonic() - started, 1e-3), heard_by(args.node)),
                  file=sys.stderr)


if __name__ == "__main__":
    main()
