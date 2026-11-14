"""Pi radio node.

Runs on the Raspberry Pi 5 as root (CONTRACTS.md §9).

Advertises as beacon S (manufacturer data FFFF 52 53 'S') every 20 ms, and scans
with duplicate filtering OFF for east and west beacons.  Forwards kept readings
to the board bus at 192.168.77.2:5600 as contract-v2 rssi messages.

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
    HCI_IFACE    HCI device index (default 0  → hci0)
    BUS_HOST     bus UDP host (default 192.168.77.2)
    BUS_PORT     bus UDP port (default 5600)

Entry point:
    sudo python -m pi.radio_node
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import struct
import sys
import time

from radio import hci
from radio.hci_scan import BeaconScanner, kept, make_bus_emitter, open_controller

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HCI_IDX: int = int(os.environ.get("HCI_IFACE", "0"))
BUS_HOST: str = os.environ.get("BUS_HOST", "192.168.77.2")
BUS_PORT: int = int(os.environ.get("BUS_PORT", "5600"))

RX = "pi5"

# 20 ms interval in 0.625 ms units: 20 / 0.625 = 32 = 0x0020
ADV_INTERVAL_HCI: int = 32

HCI_RESET = 0x0C03
LE_SET_ADV_PARAMS = 0x2006
LE_SET_ADV_DATA = 0x2008
LE_SET_ADV_ENABLE = 0x200A
LE_SET_EXT_ADV_ENABLE = 0x2039

# A Command Complete for one of these that this node didn't send means something else
# changed the controller's advertising or scanning, so ours is set up again.
WATCHED = {
    HCI_RESET, LE_SET_ADV_PARAMS, LE_SET_ADV_DATA, LE_SET_ADV_ENABLE, LE_SET_EXT_ADV_ENABLE,
    hci.LE_SET_SCAN_PARAMS, hci.LE_SET_SCAN_ENABLE, hci.LE_SET_EXT_SCAN_PARAMS, hci.LE_SET_EXT_SCAN_ENABLE,
}
SETTLE_S = 1.0    # wait this long after the last outside change before setting up again
QUIET_S = 5.0     # no advert from anything for this long: the scan was stopped, set up again
STATUS_S = 10.0   # one status line this often

_MFR_DATA = bytes.fromhex("FFFF525353")
_ADV_DATA = bytes([len(_MFR_DATA) + 1, 0xFF]) + _MFR_DATA


# ---------------------------------------------------------------------------
# Advertising commands
# ---------------------------------------------------------------------------

def build_adv_params_params() -> bytes:
    """15 parameter bytes for LE Set Advertising Parameters (20 ms, non-connectable undirected)."""
    p = bytearray(15)
    struct.pack_into("<H", p, 0, ADV_INTERVAL_HCI)
    struct.pack_into("<H", p, 2, ADV_INTERVAL_HCI)
    p[4] = 0x03   # ADV_NONCONN_IND
    p[5] = 0x00   # own address: public
    p[6] = 0x00   # peer address: public
    # bytes 7-12: peer address zeros
    p[13] = 0x07  # channel map: 37, 38, 39
    p[14] = 0x00  # filter policy: process all
    return bytes(p)


def build_adv_params_cmd() -> bytes:
    return hci.command_packet(LE_SET_ADV_PARAMS, build_adv_params_params())


def build_adv_data_params() -> bytes:
    """32 parameter bytes: length of significant data (7) + 31 padded data bytes."""
    padded = _ADV_DATA + bytes(31 - len(_ADV_DATA))
    return bytes([len(_ADV_DATA)]) + padded


def build_adv_data_cmd() -> bytes:
    return hci.command_packet(LE_SET_ADV_DATA, build_adv_data_params())


def build_adv_enable_cmd(enable: bool) -> bytes:
    return hci.command_packet(LE_SET_ADV_ENABLE, bytes([0x01 if enable else 0x00]))


def start_advertising(dev: hci.Hci) -> None:
    dev.command(LE_SET_ADV_ENABLE, bytes([0x00]), check=False)
    dev.command(LE_SET_ADV_PARAMS, build_adv_params_params())
    dev.command(LE_SET_ADV_DATA, build_adv_data_params())
    dev.command(LE_SET_ADV_ENABLE, bytes([0x01]))


def stop_advertising(dev: hci.Hci) -> None:
    dev.command(LE_SET_ADV_ENABLE, bytes([0x00]), check=False)


# ---------------------------------------------------------------------------
# Packets seen on the socket
# ---------------------------------------------------------------------------

def completed_opcode(packet: bytes):
    """The opcode a Command Complete event answers, or None for any other packet."""
    if len(packet) >= 6 and packet[0] == hci.EVENT_PKT and packet[1] == hci.EV_CMD_COMPLETE:
        return struct.unpack_from("<H", packet, 4)[0]
    return None


def is_advert(packet: bytes) -> bool:
    """True for an LE (Extended) Advertising Report from any advertiser, ours or not."""
    return (len(packet) >= 4 and packet[0] == hci.EVENT_PKT and packet[1] == hci.EV_LE_META
            and packet[3] in (hci.LE_ADV_REPORT, hci.LE_EXT_ADV_REPORT))


# ---------------------------------------------------------------------------
# Sending to the bus
# ---------------------------------------------------------------------------

class BusSender:
    """emit(link, dbm) to the bus that never raises: a reading that can't be sent is dropped and counted.

    With no Ethernet link yet, sendto fails (network unreachable); the node keeps advertising
    and scanning, and the readings flow again as soon as the link is up.
    """

    def __init__(self, sock: socket.socket, target: tuple[str, int]):
        self._emit = make_bus_emitter(sock, target, rx=RX)
        self.sent = self.failed = 0
        self.error: OSError | None = None

    def __call__(self, link: str, dbm: int) -> None:
        try:
            self._emit(link, dbm)
            self.sent += 1
        except OSError as e:
            self.failed += 1
            self.error = e


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def set_up(dev: hci.Hci, scanner: BeaconScanner) -> None:
    """Advertise beacon S and scan, from whatever state the controller is in.

    Both turn themselves off first, because their parameters can't change while they're on.
    """
    start_advertising(dev)
    scanner.start()


def status_line(counts: dict, seconds: float, bus: BusSender, redone: int) -> str:
    """Rates and sends since the last status line; how often the controller was set up again since start."""
    rates = ", ".join(f"{link} {counts.get(link, 0) / seconds:.1f}/s"
                      for link in (f"east>{RX}:ble", f"west>{RX}:ble"))
    line = f"[pi.radio_node] {rates}; sent {bus.sent}, not sent {bus.failed}"
    if bus.failed and bus.error is not None:
        line += f" ({bus.error.strerror or bus.error})"
    bus.sent = bus.failed = 0
    bus.error = None
    return line + f"; set up again {redone}x since start"


def run(dev: hci.Hci, bus_host: str = BUS_HOST, bus_port: int = BUS_PORT,
        seconds: float = 0, stop=lambda: False, seen=None, bus_sock=None,
        clock=time.monotonic, log=lambda line: print(line, file=sys.stderr, flush=True)) -> dict | None:
    """Advertise beacon S and scan for east/west beacons, forwarding rssi to the board bus.

    If given, `seen` is filled with {link: [dbm, ...]} and returned (the service passes none, so
    nothing piles up). An OSError from the HCI socket (the controller is down or gone) is raised
    to the caller; one from the bus socket never is.
    """
    own_sock = bus_sock is None
    bus_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) if own_sock else bus_sock
    bus = BusSender(bus_sock, (bus_host, bus_port))
    scanner = None
    end = clock() + seconds if seconds else None
    try:
        scanner = BeaconScanner(dev, rx=RX)
        # The Pi advertises with the legacy commands, so its scan stays legacy too: the two
        # command families must not be mixed on one controller.
        scanner.ext = False
        scanner.mode = "legacy"
        set_up(dev, scanner)
        now = clock()
        last_advert = last_status = now
        redo_at = None
        redone = 0
        quiet_told = False  # say "no adverts" once per quiet spell, not every QUIET_S
        counts: dict = {}
        while not stop() and (end is None or clock() < end):
            packet = dev.recv(0.5)
            now = clock()
            if packet:
                if is_advert(packet):
                    last_advert, quiet_told = now, False
                    for link, dbm in kept(packet, RX):
                        bus(link, dbm)
                        if seen is not None:
                            seen.setdefault(link, []).append(dbm)
                        counts[link] = counts.get(link, 0) + 1
                elif completed_opcode(packet) in WATCHED:
                    if redo_at is None:
                        log(f"[pi.radio_node] something else sent HCI command 0x{completed_opcode(packet):04X}; "
                            "setting up advertising and scanning again")
                    redo_at = now + SETTLE_S
            if redo_at is None and now - last_advert >= QUIET_S:
                if not quiet_told:
                    log(f"[pi.radio_node] no adverts for {QUIET_S:.0f} s; setting up advertising and scanning "
                        f"again every {QUIET_S:.0f} s until one arrives")
                    quiet_told = True
                redo_at = now
            if redo_at is not None and now >= redo_at:
                set_up(dev, scanner)
                redone += 1
                redo_at = None
                last_advert = clock()
            if now - last_status >= STATUS_S:
                log(status_line(counts, now - last_status, bus, redone))
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
    ap.add_argument("--seconds", type=float, default=0, help="stop after this long (0 = until Ctrl-C)")
    args = ap.parse_args(argv)

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    dev = open_controller(args.dev)

    print(
        f"[pi.radio_node] advertising beacon S, scanning on hci{args.dev}; "
        f"forwarding to {BUS_HOST}:{BUS_PORT}",
        file=sys.stderr, flush=True,
    )
    try:
        run(dev, bus_host=BUS_HOST, bus_port=BUS_PORT, seconds=args.seconds)
    except KeyboardInterrupt:
        pass
    except hci.HciError as e:
        sys.exit(f"hci{args.dev}: {e}")
    except OSError as e:
        # Powered off, rfkill'd or gone: exit non-zero so systemd starts the node again.
        sys.exit(f"hci{args.dev}: {e}. Is Bluetooth on? sudo rfkill unblock bluetooth; sudo bluetoothctl power on")
    finally:
        dev.close()


if __name__ == "__main__":
    main()
