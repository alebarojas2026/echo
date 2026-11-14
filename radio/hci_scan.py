"""Raw HCI Bluetooth scan with duplicate filtering off, keeping only our beacons.

    sudo python -m radio.hci_scan --node unoq                  # forwards rssi to bus (127.0.0.1:5600)
    sudo python -m radio.hci_scan --node unoq --seconds 60     # Gate 2: prints adverts/s per beacon link

The controller's supported commands decide the scan commands: extended scanning (LE Set Extended
Scan Parameters/Enable, reports in subevent 0x0D) if it has LE Set Extended Scan Enable, otherwise
the legacy pair (0x200B/0x200C, subevent 0x02). The two are never mixed. Either way the scan is
passive, interval = window = 10 ms, and Filter_Duplicates is 0 (btmon: "Filter duplicates: Disabled").

Only reports carrying manufacturer data FFFF 52 53 'S'|'E'|'W' are kept (radio/nodes.json); everything
else is dropped before any JSON is built, and no address ever leaves the parser.
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
from .nodes import BEACONS, LINKS

MARK = b"\xff\xff\x52\x53"  # company id FFFF + "RS": a cheap test before parsing a packet


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
            if link in LINKS:
                out.append((link, rssi))
                break
    return out


class BeaconScanner:
    """Scans on one controller and keeps our beacons' adverts as (link, dbm) for receiver `rx`."""

    def __init__(self, dev: hci.Hci, rx: str):
        self.dev, self.rx = dev, rx
        self.ext = dev.supports_ext_scan()
        self.mode = "extended" if self.ext else "legacy"

    def start(self) -> None:
        self.dev.command(*hci.scan_enable(self.ext, False), check=False)  # params can't change while on
        self.dev.command(*hci.scan_params(self.ext))
        self.dev.command(*hci.scan_enable(self.ext, True))

    def stop(self) -> None:
        self.dev.command(*hci.scan_enable(self.ext, False), check=False)

    def poll(self, timeout: float = 0.5):
        packet = self.dev.recv(timeout)
        return kept(packet, self.rx) if packet else []


def make_bus_emitter(sock: socket.socket, target: tuple[str, int], rx: str):
    """Return an emit(link, dbm) callback that sends contract-v2 rssi messages to `target` over UDP with seq."""
    seq = 0

    def emit(link: str, dbm: int):
        nonlocal seq
        tx = LINKS[link]["tx"]
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


def run(scanner: BeaconScanner, emit, seconds: float = 0, stop=lambda: False, seen=None,
        quiet_s: float = 2.0, clock=time.monotonic, say=None) -> dict:
    """Scan, calling emit(link, dbm) per kept advert, until `seconds` pass (0 = forever) or stop().

    Fills and returns `seen` = {link: [dbm, ...]}, which keeps what was read even after Ctrl-C.
    The scan is always turned off on the way out.

    Scanning is one setting for the whole controller, and other things turn it off: another scan
    exiting, bluetoothctl, the kernel's own background-scan check after a Bluetooth power cycle.
    So when none of our beacons has been heard for quiet_s, the scan is started again (and again
    every quiet_s while it stays quiet). It's said once per quiet stretch, and again when adverts
    come back.
    """
    say = say or (lambda text: print(text, file=sys.stderr, flush=True))
    seen = {} if seen is None else seen
    end = clock() + seconds if seconds else None
    scanner.start()
    last = quiet_since = clock()
    restarted = False
    try:
        while not stop() and (end is None or clock() < end):
            kept_now = scanner.poll()
            now = clock()
            if kept_now:
                if restarted:
                    say(f"beacon adverts back after {now - quiet_since:.0f} s")
                    restarted = False
                last = now
            for link, dbm in kept_now:
                emit(link, dbm)
                seen.setdefault(link, []).append(dbm)
            if quiet_s and now - last >= quiet_s:
                if not restarted:
                    say(f"no beacon adverts for {quiet_s:g} s, restarting the scan")
                    restarted, quiet_since = True, last
                scanner.start()
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
    ap.add_argument("--node", required=True, choices=["unoq", "pi5"], help="the receiver this runs on")
    ap.add_argument("--dev", type=int, default=0, help="HCI device number (0 = hci0)")
    ap.add_argument("--seconds", type=float, default=0, help="stop after this long (0 = until Ctrl-C)")
    args = ap.parse_args(argv)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))  # a service stop still turns the scan off
    dev = open_controller(args.dev)
    seen, started = {}, time.monotonic()

    bus_host = os.environ.get("BUS_HOST", "127.0.0.1")
    bus_port = int(os.environ.get("BUS_PORT", "5600"))
    bus_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    emitter = make_bus_emitter(bus_sock, (bus_host, bus_port), args.node)

    try:
        scanner = BeaconScanner(dev, args.node)
        print(f"hci{args.dev}: {scanner.mode} scan, duplicates not filtered, rx {args.node}", file=sys.stderr)
        run(scanner, emitter, args.seconds, seen=seen)
    except KeyboardInterrupt:
        pass
    except hci.HciError as e:
        sys.exit(f"hci{args.dev}: {e}")
    finally:
        bus_sock.close()
        dev.close()
    print(summary(seen, max(time.monotonic() - started, 1e-3)), file=sys.stderr)


if __name__ == "__main__":
    main()
