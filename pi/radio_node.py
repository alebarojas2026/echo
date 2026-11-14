"""Pi radio node.

Runs on the Raspberry Pi 5 as root (CONTRACTS.md §9).

Advertises as beacon S (manufacturer data FFFF 52 53 'S') every 20 ms, and scans
with duplicate filtering OFF for east and west beacons.  Forwards kept readings
to the board bus at 192.168.77.2:5600 as contract-v2 rssi messages.

Matching is by advertised manufacturer data, never by MAC address.
No MACs, BSSIDs or local secrets are stored here.

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
from radio.hci_scan import BeaconScanner, make_bus_emitter, open_controller, run as run_scan

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HCI_IDX: int = int(os.environ.get("HCI_IFACE", "0"))
BUS_HOST: str = os.environ.get("BUS_HOST", "192.168.77.2")
BUS_PORT: int = int(os.environ.get("BUS_PORT", "5600"))

# 20 ms interval in 0.625 ms units: 20 / 0.625 = 32 = 0x0020
ADV_INTERVAL_HCI: int = 32

LE_SET_ADV_PARAMS = 0x2006
LE_SET_ADV_DATA = 0x2008
LE_SET_ADV_ENABLE = 0x200A

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
# Main loop
# ---------------------------------------------------------------------------

def run(dev: hci.Hci, bus_host: str = BUS_HOST, bus_port: int = BUS_PORT,
        seconds: float = 0, stop=lambda: False, seen=None) -> dict:
    """Advertise beacon S and scan for east/west beacons, forwarding rssi to the board bus."""
    bus_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    emitter = make_bus_emitter(bus_sock, (bus_host, bus_port), rx="pi5")
    start_advertising(dev)
    scanner = BeaconScanner(dev, rx="pi5")
    scanner.ext = False
    scanner.mode = "legacy"
    try:
        return run_scan(scanner, emitter, seconds=seconds, stop=stop, seen=seen)
    finally:
        stop_advertising(dev)
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
        file=sys.stderr,
    )
    try:
        run(dev, bus_host=BUS_HOST, bus_port=BUS_PORT, seconds=args.seconds)
    except KeyboardInterrupt:
        pass
    except hci.HciError as e:
        sys.exit(f"hci{args.dev}: {e}")
    finally:
        dev.close()


if __name__ == "__main__":
    main()
