"""Board-side Bluetooth LE scanner for the UNO Q (north node).

Runs as root (CONTRACTS.md §9):
    sudo python -m radio.hci_scan --node unoq

Opens a raw HCI socket with duplicate filtering OFF (confirmed in btmon as
"Filter duplicates: Disabled").  Keeps only advertisements whose manufacturer
data matches one of our three beacon payloads (CONTRACTS.md §3), matched by
data only, never by MAC address.  Emits a contract-v2 ``rssi`` message for
each kept advertisement to the bus UDP socket at 127.0.0.1:5600.

Links produced (rx = this node):
    pi5>unoq:ble   pi5  → unoq
    east>unoq:ble  east → unoq
    west>unoq:ble  west → unoq

Environment variables (set in .env, gitignored):
    HCI_IFACE   HCI device index (default 0 → hci0)
    BUS_HOST    bus UDP host (default 127.0.0.1)
    BUS_PORT    bus UDP port (default 5600)
    RATE_HZ     (unused for BLE; kept for consistency)

Usage:
    sudo python -m radio.hci_scan --node unoq
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import struct
import time


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HCI_IDX: int = int(os.environ.get("HCI_IFACE", "0"))
BUS_HOST: str = os.environ.get("BUS_HOST", "127.0.0.1")
BUS_PORT: int = int(os.environ.get("BUS_PORT", "5600"))

# Beacon payloads → (tx_node, link_id) when rx = "unoq"
# Matched by manufacturer data, never by MAC (CONTRACTS.md §3).
BEACON_LINKS: dict[bytes, tuple[str, str]] = {
    bytes.fromhex("FFFF525353"): ("pi5",  "pi5>unoq:ble"),   # S
    bytes.fromhex("FFFF525345"): ("east", "east>unoq:ble"),  # E
    bytes.fromhex("FFFF525357"): ("west", "west>unoq:ble"),  # W
}

# ---------------------------------------------------------------------------
# HCI constants (duplicated from pi.radio_node so this module is self-contained)
# ---------------------------------------------------------------------------

BTPROTO_HCI = 1
SOL_HCI = 0
HCI_FILTER = 2
HCI_EVENT_PKT = 0x04
EVT_LE_META_EVENT = 0x3E
EVT_LE_ADVERTISING_REPORT = 0x02
CMD_PKT = 0x01

OGF_LE = 0x08
OCF_LE_SET_SCAN_PARAMS = 0x000B
OCF_LE_SET_SCAN_ENABLE = 0x000C


def _opcode(ogf: int, ocf: int) -> int:
    return (ogf << 10) | ocf


def _hci_command(opcode: int, params: bytes) -> bytes:
    return struct.pack("<BHB", CMD_PKT, opcode, len(params)) + params


def _scan_params_cmd() -> bytes:
    """LE Set Scan Parameters: passive, 10 ms window, accept all."""
    return _hci_command(
        _opcode(OGF_LE, OCF_LE_SET_SCAN_PARAMS),
        struct.pack("<BHHBB", 0x00, 0x0010, 0x0010, 0x00, 0x00),
    )


def _scan_enable_cmd(enable: bool, filter_dupes: bool = False) -> bytes:
    """LE Set Scan Enable.  filter_dupes=False keeps every advertisement."""
    return _hci_command(
        _opcode(OGF_LE, OCF_LE_SET_SCAN_ENABLE),
        bytes([0x01 if enable else 0x00, 0x01 if filter_dupes else 0x00]),
    )


def _hci_filter_events() -> bytes:
    type_mask = 1 << HCI_EVENT_PKT
    event_mask = (1 << 63) - 1
    return struct.pack("<IQH", type_mask, event_mask, 0)


# ---------------------------------------------------------------------------
# AD structure parser
# ---------------------------------------------------------------------------

def extract_mfr_data(payload: bytes) -> bytes | None:
    """Return manufacturer data bytes from an AD payload, or None."""
    i = 0
    while i < len(payload):
        length = payload[i]
        if length == 0 or i + length >= len(payload):
            break
        ad_type = payload[i + 1]
        data = payload[i + 2: i + 1 + length]
        if ad_type == 0xFF:
            return data
        i += 1 + length
    return None


def parse_adv_reports(data: bytes) -> list[tuple[bytes, int]]:
    """Parse LE Advertising Report subevent, return [(mfr_data, rssi_dbm)]."""
    results: list[tuple[bytes, int]] = []
    if not data:
        return results
    num = data[0]
    pos = 1
    for _ in range(num):
        if pos + 9 > len(data):
            break
        data_len = data[pos + 8]
        pos += 9
        if pos + data_len + 1 > len(data):
            break
        adv_payload = data[pos: pos + data_len]
        rssi_raw = data[pos + data_len]
        rssi = rssi_raw - 256 if rssi_raw > 127 else rssi_raw
        pos += data_len + 1
        mfr = extract_mfr_data(adv_payload)
        if mfr is not None:
            results.append((mfr, rssi))
    return results


# ---------------------------------------------------------------------------
# Bus publisher
# ---------------------------------------------------------------------------

def _make_rssi_message(link_id: str, tx: str, rx: str, dbm: int, seq: int) -> bytes:
    return json.dumps({
        "v": 2,
        "type": "rssi",
        "t": int(time.time() * 1000),
        "seq": seq,
        "src": "live",
        "link": link_id,
        "kind": "ble",
        "tx": tx,
        "rx": rx,
        "dbm": dbm,
    }, separators=(",", ":")).encode()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(node: str = "unoq",
        hci_idx: int = HCI_IDX,
        bus_host: str = BUS_HOST,
        bus_port: int = BUS_PORT) -> None:
    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_RAW, BTPROTO_HCI)
    sock.bind((hci_idx,))
    sock.setsockopt(SOL_HCI, HCI_FILTER, _hci_filter_events())

    bus = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    seq = 0

    sock.send(_scan_params_cmd())
    time.sleep(0.05)
    # Duplicate filtering OFF — btmon will show "Filter duplicates: Disabled"
    sock.send(_scan_enable_cmd(True, filter_dupes=False))
    time.sleep(0.05)

    print(
        f"[hci_scan] node={node} hci{hci_idx} scanning; "
        f"duplicates OFF; -> {bus_host}:{bus_port}",
        flush=True,
    )

    sock.settimeout(1.0)
    while True:
        try:
            pkt = sock.recv(300)
        except socket.timeout:
            continue
        if len(pkt) < 4 or pkt[0] != HCI_EVENT_PKT:
            continue
        if pkt[1] != EVT_LE_META_EVENT or pkt[3] != EVT_LE_ADVERTISING_REPORT:
            continue
        for mfr_data, rssi in parse_adv_reports(pkt[4:]):
            if mfr_data not in BEACON_LINKS:
                continue
            tx, link_id = BEACON_LINKS[mfr_data]
            payload = _make_rssi_message(link_id, tx, node, rssi, seq)
            bus.sendto(payload, (bus_host, bus_port))
            seq += 1


def main() -> None:
    parser = argparse.ArgumentParser(description="BLE scanner for the UNO Q board node")
    parser.add_argument("--node", default="unoq",
                        help="Receiving node id (default: unoq)")
    args = parser.parse_args()
    run(node=args.node)


if __name__ == "__main__":
    main()
