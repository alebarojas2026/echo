"""Pi radio node.

Runs on the Raspberry Pi 5 as root (CONTRACTS.md §9).

Two things happen concurrently:
  1. Advertise: the Pi broadcasts as beacon "S" every 20 ms using a raw HCI
     LE Set Advertising Data + LE Set Advertise Enable sequence.
  2. Scan: raw HCI LE scan with duplicate filtering OFF.  Every advertisement
     whose manufacturer data matches one of our three beacon payloads is
     decoded and forwarded as a contract-v2 ``rssi`` message over UDP to the
     board's bus at 192.168.77.2:5600.

Beacon matching is by advertised manufacturer data, never by MAC address.
No MACs, BSSIDs or IP addresses beyond those in CONTRACTS.md are stored here.

Environment variables (set in /etc/deadzone.env, gitignored):
    HCI_IFACE    HCI device index (default 0  → hci0)
    BUS_HOST     bus UDP host (default 192.168.77.2)
    BUS_PORT     bus UDP port (default 5600)

Entry point:
    sudo python -m pi.radio_node
"""

from __future__ import annotations

import json
import os
import socket
import struct
import threading
import time

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HCI_IDX: int = int(os.environ.get("HCI_IFACE", "0"))
BUS_HOST: str = os.environ.get("BUS_HOST", "192.168.77.2")
BUS_PORT: int = int(os.environ.get("BUS_PORT", "5600"))

# Advertise every 20 ms (50 Hz).  HCI interval units = 0.625 ms.
ADV_INTERVAL_HCI: int = round(20 / 0.625)   # 32 = 20 ms

# Beacon payloads from nodes.json / CONTRACTS.md §3.
# company_id FFFF + prefix RS (0x52 0x53) + node letter.
BEACON_PAYLOADS: dict[bytes, tuple[str, str]] = {
    bytes.fromhex("FFFF525353"): ("pi5",  "pi5>unoq:ble"),   # S
    bytes.fromhex("FFFF525345"): ("east", "east>unoq:ble"),  # E
    bytes.fromhex("FFFF525357"): ("west", "west>unoq:ble"),  # W
}

# The Pi is the tx for its own beacon on both board-side and Pi-side links.
# When the Pi scans, it only captures readings at the Pi (rx = pi5).
# The board's hci_scan captures east>unoq:ble and west>unoq:ble at the board.
# Here we forward east>pi5:ble and west>pi5:ble; pi5>unoq:ble is not visible
# to the Pi itself (it is the transmitter).
PI_RX_LINKS: dict[bytes, tuple[str, str, str]] = {
    bytes.fromhex("FFFF525345"): ("east", "pi5", "east>pi5:ble"),  # E heard at Pi
    bytes.fromhex("FFFF525357"): ("west", "pi5", "west>pi5:ble"),  # W heard at Pi
}

# ---------------------------------------------------------------------------
# HCI socket constants
# ---------------------------------------------------------------------------

HCI_CHANNEL_RAW = 0
BTPROTO_HCI = 1
SOL_HCI = 0
HCI_FILTER = 2

# HCI event codes
HCI_EVENT_PKT = 0x04
EVT_LE_META_EVENT = 0x3E
EVT_LE_ADVERTISING_REPORT = 0x02

# HCI command opcodes
OGF_LE = 0x08
OCF_LE_SET_ADV_PARAMS   = 0x0006
OCF_LE_SET_ADV_DATA     = 0x0008
OCF_LE_SET_SCAN_RESP    = 0x0009
OCF_LE_SET_ADV_ENABLE   = 0x000A
OCF_LE_SET_SCAN_PARAMS  = 0x000B
OCF_LE_SET_SCAN_ENABLE  = 0x000C

CMD_PKT = 0x01


def _opcode(ogf: int, ocf: int) -> int:
    return (ogf << 10) | ocf


def _hci_command(opcode: int, params: bytes) -> bytes:
    return struct.pack("<BHB", CMD_PKT, opcode, len(params)) + params


# ---------------------------------------------------------------------------
# Advertising
# ---------------------------------------------------------------------------

# Our manufacturer data: type 0xFF, company FFFF, payload RS + 'S'
_MFR_DATA = bytes.fromhex("FFFF525353")
_ADV_DATA = (
    bytes([len(_MFR_DATA) + 1, 0xFF]) + _MFR_DATA
)

def _build_adv_data_cmd() -> bytes:
    """LE Set Advertising Data (pad to 31 bytes)."""
    padded = _ADV_DATA + bytes(31 - len(_ADV_DATA))
    params = bytes([len(_ADV_DATA)]) + padded
    return _hci_command(_opcode(OGF_LE, OCF_LE_SET_ADV_DATA), params)


def _build_adv_params_cmd() -> bytes:
    """LE Set Advertising Parameters: non-connectable undirected, 20 ms."""
    params = struct.pack(
        "<HHBBBBBBhB",
        ADV_INTERVAL_HCI,  # min interval
        ADV_INTERVAL_HCI,  # max interval
        0x03,              # ADV_NONCONN_IND
        0x00,              # own address type: public
        0x00,              # peer address type
        0, 0, 0, 0, 0, 0, # peer address (unused)
        0x07,              # channel map: all three
        0x00,              # filter policy: none
    )
    # Struct packs 10 ints; actual HCI params are 15 bytes.
    # Build manually to avoid struct alignment issues.
    p = bytearray(15)
    struct.pack_into("<H", p, 0, ADV_INTERVAL_HCI)
    struct.pack_into("<H", p, 2, ADV_INTERVAL_HCI)
    p[4] = 0x03   # ADV_NONCONN_IND
    p[5] = 0x00   # own address: public
    p[6] = 0x00   # peer address: public
    # bytes 7-12: peer address (zeros)
    p[13] = 0x07  # all channels
    p[14] = 0x00  # filter policy
    return _hci_command(_opcode(OGF_LE, OCF_LE_SET_ADV_PARAMS), bytes(p))


def _adv_enable_cmd(enable: bool) -> bytes:
    return _hci_command(_opcode(OGF_LE, OCF_LE_SET_ADV_ENABLE),
                        bytes([0x01 if enable else 0x00]))


def _start_advertising(sock: socket.socket) -> None:
    sock.send(_build_adv_params_cmd())
    time.sleep(0.05)
    sock.send(_build_adv_data_cmd())
    time.sleep(0.05)
    sock.send(_adv_enable_cmd(True))
    time.sleep(0.05)


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def _build_scan_params_cmd() -> bytes:
    """LE Set Scan Parameters: passive scan, no duplicate filtering."""
    # scan_type=0 passive, interval=0x0010 (10ms), window=0x0010 (10ms),
    # own_addr=public, filter=accept all
    p = struct.pack("<BHHBB", 0x00, 0x0010, 0x0010, 0x00, 0x00)
    return _hci_command(_opcode(OGF_LE, OCF_LE_SET_SCAN_PARAMS), p)


def _build_scan_enable_cmd(enable: bool, filter_dupes: bool = False) -> bytes:
    """LE Set Scan Enable.  filter_dupes=False keeps all duplicates."""
    p = bytes([0x01 if enable else 0x00, 0x01 if filter_dupes else 0x00])
    return _hci_command(_opcode(OGF_LE, OCF_LE_SET_SCAN_ENABLE), p)


def _hci_filter_all_events() -> bytes:
    """Build an HCI filter that passes all event packets."""
    # struct hci_filter: type_mask, event_mask[2], opcode
    type_mask = 1 << HCI_EVENT_PKT
    event_mask = (1 << 63) - 1  # all events
    opcode = 0
    return struct.pack("<IQH", type_mask, event_mask, opcode)


def _extract_mfr_data(payload: bytes) -> bytes | None:
    """Walk AD structures, return manufacturer data payload or None."""
    i = 0
    while i < len(payload):
        if i >= len(payload):
            break
        length = payload[i]
        if length == 0 or i + length >= len(payload):
            break
        ad_type = payload[i + 1]
        data = payload[i + 2: i + 1 + length]
        if ad_type == 0xFF:  # Manufacturer Specific Data
            return data
        i += 1 + length
    return None


def _parse_adv_report(data: bytes) -> list[tuple[bytes, int]]:
    """Parse an LE Advertising Report subevent, return [(mfr_data, rssi)]."""
    results = []
    if len(data) < 2:
        return results
    num_reports = data[0]
    pos = 1
    for _ in range(num_reports):
        if pos + 9 > len(data):
            break
        # event_type(1) addr_type(1) addr(6) data_len(1)
        data_len = data[pos + 8]
        pos += 9
        if pos + data_len + 1 > len(data):
            break
        adv_payload = data[pos: pos + data_len]
        rssi_raw = data[pos + data_len]
        rssi = rssi_raw - 256 if rssi_raw > 127 else rssi_raw
        pos += data_len + 1
        mfr = _extract_mfr_data(adv_payload)
        if mfr is not None:
            results.append((mfr, rssi))
    return results


# ---------------------------------------------------------------------------
# Bus publisher
# ---------------------------------------------------------------------------

class _Publisher:
    def __init__(self, host: str, port: int) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._addr = (host, port)
        self._seq = 0

    def publish(self, link_id: str, tx: str, rx: str, dbm: int) -> None:
        msg = {
            "v": 2,
            "type": "rssi",
            "t": int(time.time() * 1000),
            "seq": self._seq,
            "src": "live",
            "link": link_id,
            "kind": "ble",
            "tx": tx,
            "rx": rx,
            "dbm": dbm,
        }
        self._sock.sendto(
            json.dumps(msg, separators=(",", ":")).encode(),
            self._addr,
        )
        self._seq += 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _open_hci_socket(idx: int) -> socket.socket:
    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_RAW, BTPROTO_HCI)
    sock.bind((idx,))
    sock.setsockopt(SOL_HCI, HCI_FILTER, _hci_filter_all_events())
    return sock


def run(hci_idx: int = HCI_IDX,
        bus_host: str = BUS_HOST,
        bus_port: int = BUS_PORT) -> None:
    pub = _Publisher(bus_host, bus_port)

    adv_sock = _open_hci_socket(hci_idx)
    scan_sock = _open_hci_socket(hci_idx)

    _start_advertising(adv_sock)

    scan_sock.send(_build_scan_params_cmd())
    time.sleep(0.05)
    scan_sock.send(_build_scan_enable_cmd(True, filter_dupes=False))

    print(
        f"[pi.radio_node] advertising as beacon S, scanning on hci{hci_idx}; "
        f"forwarding to {bus_host}:{bus_port}",
        flush=True,
    )

    scan_sock.settimeout(1.0)
    while True:
        try:
            pkt = scan_sock.recv(300)
        except socket.timeout:
            continue
        # pkt[0] = HCI_EVENT_PKT (0x04)
        if len(pkt) < 4 or pkt[0] != HCI_EVENT_PKT:
            continue
        event_code = pkt[1]
        # pkt[2] = parameter total length, pkt[3] = subevent code
        if event_code != EVT_LE_META_EVENT or pkt[3] != EVT_LE_ADVERTISING_REPORT:
            continue
        reports = _parse_adv_report(pkt[4:])
        for mfr_data, rssi in reports:
            # Prepend company id bytes that _extract_mfr_data strips the type byte for.
            # Actually _extract_mfr_data returns everything after the AD type byte,
            # so mfr_data = company_id(2) + payload.
            key = bytes([0xFF, 0xFF]) + mfr_data[2:] if len(mfr_data) >= 2 else b""
            # Try exact match first (mfr_data as returned includes company id)
            full_key = mfr_data  # already company_id + payload
            if full_key in PI_RX_LINKS:
                tx, rx, link_id = PI_RX_LINKS[full_key]
                pub.publish(link_id, tx, rx, rssi)


def main() -> None:
    run()


if __name__ == "__main__":
    main()
