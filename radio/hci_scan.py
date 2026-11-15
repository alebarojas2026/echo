"""Raw HCI Bluetooth scan with duplicate filtering off, keeping only our beacons.

    sudo python -m radio.hci_scan --node unoq                  # forwards rssi to bus (127.0.0.1:5600)
    sudo python -m radio.hci_scan --node unoq --seconds 60     # Gate 2: prints adverts/s per beacon link

The controller's supported commands decide the scan commands: extended scanning (LE Set Extended
Scan Parameters/Enable, reports in subevent 0x0D) if it has LE Set Extended Scan Enable, otherwise
the legacy pair (0x200B/0x200C, subevent 0x02). The two are never mixed. Either way the scan is
passive, interval = window = 10 ms, and Filter_Duplicates is 0 (btmon: "Filter duplicates: Disabled").

Scanning is one setting for the whole controller. When something else changes it (bluetoothd or the
kernel setting its own scan, which is half duty and filters duplicates; an HCI Reset), the scan is set
up again with ours 1 s after the last outside change, and the journal says so.

Only reports carrying manufacturer data FFFF 52 53 'S'|'E'|'W' are kept (radio/nodes.json), plus the
optional hall beacons listed there ('H'|'J'); everything else is dropped before any JSON is built, and
no address ever leaves the parser.
"""
import argparse
import json
import os
import signal
import socket
import statistics
import sys
import time

from . import hci
from .nodes import BEACONS, HEARD, LINKS, RECEIVERS

MARK = b"\xff\xff\x52\x53"  # company id FFFF + "RS": a cheap test before parsing a packet

# A Command Complete for one of these that the scanner didn't send means something else changed the
# controller's scan (our own replies are read inside Hci.command, never by poll()).
OUTSIDE = {hci.HCI_RESET, hci.LE_SET_SCAN_PARAMS, hci.LE_SET_SCAN_ENABLE,
           hci.LE_SET_EXT_SCAN_PARAMS, hci.LE_SET_EXT_SCAN_ENABLE}
SETTLE_S = 1.0       # set ours up again this long after the last outside change
SAY_EVERY_S = 60.0   # say an outside change at most this often (with a count)


def kept(packet: bytes, rx: str):
    """[(link, dbm)] for the reports in one HCI packet that come from our beacons, heard by `rx`."""
    if MARK not in packet:
        return []
    out = []
    for data, rssi in hci.adv_reports(packet):
        if rssi == hci.RSSI_UNAVAILABLE:
            continue
        for payload in hci.manufacturer_data(data):
            link = f"{BEACONS.get(payload)}>{rx}:ble"
            if link in HEARD:
                out.append((link, rssi))
                break
    return out


class BeaconScanner:
    """Scans on one controller and keeps our beacons' adverts as (link, dbm) for receiver `rx`."""

    def __init__(self, dev: hci.Hci, rx: str):
        self.dev, self.rx = dev, rx
        self.ext = dev.supports_ext_scan()
        self.mode = "extended" if self.ext else "legacy"
        self.outside = None  # the opcode of the last scan command something else sent, until run() takes it

    def start(self) -> None:
        self.dev.command(*hci.scan_enable(self.ext, False), check=False)  # params can't change while on
        self.dev.command(*hci.scan_params(self.ext))
        self.dev.command(*hci.scan_enable(self.ext, True))

    def stop(self) -> None:
        self.dev.command(*hci.scan_enable(self.ext, False), check=False)

    def poll(self, timeout: float = 0.5):
        packet = self.dev.recv(timeout)
        if not packet:
            return []
        if hci.completed_opcode(packet) in OUTSIDE:
            self.outside = hci.completed_opcode(packet)
            return []
        return kept(packet, self.rx)


def make_bus_emitter(sock: socket.socket, target: tuple[str, int], rx: str):
    """Return an emit(link, dbm) callback that sends contract-v2 rssi messages to `target` over UDP with seq."""
    seq = 0

    def emit(link: str, dbm: int):
        nonlocal seq
        tx = HEARD[link]["tx"]
        msg = {
            "v": 2,
            "type": "rssi",
            "t": int(time.time() * 1000),
            "seq": seq,
            "src": "live",
            "link": link,
            "kind": "ble",
            "tx": tx,
            "rx": rx,
            "dbm": dbm,
        }
        sock.sendto(json.dumps(msg, separators=(",", ":")).encode(), target)
        seq += 1

    return emit


REFUSED = {0x01, 0x0C}  # Unknown HCI Command, Command Disallowed


def start_either(scanner: BeaconScanner, say) -> None:
    """Start the scan. If the controller refuses this command family, start once with the other.

    After the host has used one family (legacy or extended) since power-on, the controller answers
    the other with Command Disallowed (Core spec Vol 4 Part E 3.1.1), and the kernel may have picked
    differently from us. Any other error, or a second refusal, is raised.
    """
    try:
        scanner.start()
    except hci.HciError as e:
        if e.status not in REFUSED:
            raise
        scanner.ext = not scanner.ext
        scanner.mode = "extended" if scanner.ext else "legacy"
        say(f"scan refused ({e}); using the {scanner.mode} commands")
        scanner.start()


def run(scanner: BeaconScanner, emit, seconds: float = 0, stop=lambda: False, seen=None,
        quiet_s: float = 2.0, clock=time.monotonic, say=None, keep: bool = True) -> dict | None:
    """Scan, calling emit(link, dbm) per kept advert, until `seconds` pass (0 = forever) or stop().

    Fills and returns `seen` = {link: [dbm, ...]}, which keeps what was read even after Ctrl-C.
    With keep False (the service, which runs for ever) nothing is kept and it returns None.
    The scan is always turned off on the way out.

    Scanning is one setting for the whole controller, and other things turn it off: another scan
    exiting, bluetoothctl, the kernel's own background-scan check after a Bluetooth power cycle.
    So when none of our beacons has been heard for quiet_s, the scan is started again (and again
    every quiet_s while it stays quiet). It's said once per quiet stretch, and again when adverts
    come back.

    In a crowded hall the radio is busy: a restart can time out or be refused for a moment, and the
    bus socket can fail a send. Neither ends the scan. A failed restart is said once per quiet
    stretch and tried again after quiet_s; a failed send drops that reading and is said once until
    a send works again. Only the controller itself going away (OSError from the HCI socket) ends it.

    When something else changes the scan (scanner.outside), ours is set up again SETTLE_S after
    the last such change, without waiting for the quiet: another scan can keep some adverts coming
    at half duty, with duplicates filtered. It's said at most once every SAY_EVERY_S, with a count.
    """
    say = say or (lambda text: print(text, file=sys.stderr, flush=True))
    seen = ({} if seen is None else seen) if keep else None
    end = clock() + seconds if seconds else None
    start_either(scanner, say)
    last = quiet_since = clock()
    restarted = restart_failed = send_failed = False
    redo_at, changed, said_at = None, 0, None
    try:
        while not stop() and (end is None or clock() < end):
            kept_now = scanner.poll()
            now = clock()
            outside = getattr(scanner, "outside", None)
            if outside is not None:
                scanner.outside = None
                changed += 1
                if said_at is None or now - said_at >= SAY_EVERY_S:
                    say(f"something else changed the scan (HCI command 0x{outside:04X}, {changed}x since start); "
                        f"setting ours up again in {SETTLE_S:g} s")
                    said_at = now
                redo_at = now + SETTLE_S
            if redo_at is not None and now >= redo_at:
                redo_at = None
                try:
                    scanner.start()
                except hci.HciError as e:
                    say(f"setting the scan up again failed ({e}); the quiet check tries again")
            if kept_now:
                if restarted:
                    say(f"beacon adverts back after {now - quiet_since:.0f} s")
                    restarted = False
                last = now
            for link, dbm in kept_now:
                try:
                    emit(link, dbm)
                    if send_failed:
                        say("sending to the bus again")
                        send_failed = False
                except OSError as e:
                    if not send_failed:
                        say(f"can't send to the bus ({e}); dropping readings until it works")
                        send_failed = True
                if seen is not None:
                    seen.setdefault(link, []).append(dbm)
            if quiet_s and now - last >= quiet_s:
                if not restarted:
                    say(f"no beacon adverts for {quiet_s:g} s, restarting the scan")
                    restarted, quiet_since, restart_failed = True, last, False
                try:
                    scanner.start()
                except hci.HciError as e:
                    if not restart_failed:
                        say(f"restarting the scan failed ({e}); trying again every {quiet_s:g} s")
                        restart_failed = True
                last = now
    finally:
        scanner.stop()
    return seen


def summary(seen: dict, seconds: float) -> str:
    """One line per beacon link: readings, adverts/s and median dBm, for the Gate 2 table in radio/GATE.md."""
    lines = [f"{'link':<15} {'n':>6} {'adverts/s':>10} {'median dBm':>11}"]
    for link in (link for link in LINKS if seen.get(link)):
        values = seen[link]
        lines.append(f"{link:<15} {len(values):>6} {len(values) / seconds:>10.1f} {statistics.median(values):>11.1f}")
    return "\n".join(lines)


def open_controller(dev: int) -> hci.Hci:
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        sys.exit("hci_scan needs root for a raw HCI socket: run it with sudo")
    try:
        return hci.Hci.open(dev)
    except OSError as e:
        sys.exit(f"can't open hci{dev}: {e}. Is Bluetooth on? Try: sudo rfkill unblock bluetooth; "
                 "sudo bluetoothctl power on")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--node", required=True, choices=RECEIVERS, help="the receiver this runs on")
    ap.add_argument("--dev", type=int, default=0, help="HCI device number (0 = hci0)")
    ap.add_argument("--seconds", type=float, default=0, help="stop after this long (0 = until Ctrl-C)")
    args = ap.parse_args(argv)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))  # a service stop still turns the scan off
    dev = open_controller(args.dev)
    # Readings are kept for the summary of a --seconds run only: the service runs for ever.
    seen, started = ({} if args.seconds else None), time.monotonic()

    bus_host = os.environ.get("BUS_HOST", "127.0.0.1")
    bus_port = int(os.environ.get("BUS_PORT", "5600"))
    bus_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    emitter = make_bus_emitter(bus_sock, (bus_host, bus_port), args.node)

    try:
        scanner = BeaconScanner(dev, args.node)
        print(f"hci{args.dev}: {scanner.mode} scan, duplicates not filtered, rx {args.node}", file=sys.stderr)
        run(scanner, emitter, args.seconds, seen=seen, keep=seen is not None)
    except KeyboardInterrupt:
        pass
    except hci.HciError as e:
        sys.exit(f"hci{args.dev}: {e}")
    except OSError as e:  # the adapter went down or away; systemd starts the service again
        sys.exit(f"hci{args.dev}: {e}. Is Bluetooth on? (sudo bluetoothctl power on)")
    finally:
        bus_sock.close()
        dev.close()
    if seen is not None:
        print(summary(seen, max(time.monotonic() - started, 1e-3)), file=sys.stderr)


if __name__ == "__main__":
    main()
