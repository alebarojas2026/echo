"""Wi-Fi RSSI reader for the UNO Q (north node).

Reads the received-signal-strength of the pi5>unoq:wifi link by polling
``iw dev <iface> station get <bssid>`` at a target rate and publishing
contract-v2 ``rssi`` messages to the bus.

Sends a message only when `rx packets:` increases since the previous poll.
When no new packets have arrived, the reading is skipped and `seq` does not
advance.

Entry point (CONTRACTS.md §9):
    python -m radio.wifi_rssi

The BSSID of the Pi's hotspot and the wireless interface name are taken
from environment variables so they never enter the repo:

    WIFI_IFACE   wlan interface joined to the sensing hotspot (e.g. wlan0)
    WIFI_BSSID   Pi's hotspot BSSID  (never committed)
    BUS_HOST     bus UDP host (default 127.0.0.1)
    BUS_PORT     bus UDP port (default 5600)
    RATE_HZ      target poll rate    (default 25)
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import time


# ---------------------------------------------------------------------------
# Configuration (all from env so no secrets land in the repo)
# ---------------------------------------------------------------------------

IFACE: str = os.environ.get("WIFI_IFACE", "wlan0")
BSSID: str = os.environ.get("WIFI_BSSID") or os.environ.get("SENSING_BSSID", "")
BUS_HOST: str = os.environ.get("BUS_HOST", "127.0.0.1")
BUS_PORT: int = int(os.environ.get("BUS_PORT", "5600"))
RATE_HZ: float = float(os.environ.get("RATE_HZ", "25"))

LINK_ID = "pi5>unoq:wifi"
TX = "pi5"
RX = "unoq"
KIND = "wifi"

# The "signal:" line itself, never "signal avg:" or "last ack signal:" (the Pi's ACKs to our own frames).
# ath10k reports chains, so iw prints "signal: -71 [-71, -74] dBm": take the number before the brackets.
_SIGNAL_RE = re.compile(r"^\s*signal:\s*(-?\d+)", re.M)
_RX_PACKETS_RE = re.compile(r"rx packets:\s+(\d+)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_station_output(text: str) -> tuple[int | None, int | None]:
    """Parse signal dBm and rx packets counter from iw station output."""
    m_sig = _SIGNAL_RE.search(text)
    m_rx = _RX_PACKETS_RE.search(text)
    dbm = int(m_sig.group(1)) if m_sig else None
    rx_pkts = int(m_rx.group(1)) if m_rx else None
    return dbm, rx_pkts


def _read_station_info(iface: str, bssid: str) -> tuple[int | None, int | None]:
    """Return (dbm, rx_packets) or (None, None) on failure."""
    try:
        out = subprocess.check_output(
            ["iw", "dev", iface, "station", "get", bssid],
            stderr=subprocess.DEVNULL,
            timeout=0.5,
        ).decode()
    except Exception:
        return None, None
    return parse_station_output(out)


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


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(iface: str = IFACE, bssid: str = BSSID,
        bus_host: str = BUS_HOST, bus_port: int = BUS_PORT,
        rate_hz: float = RATE_HZ) -> None:
    if not bssid:
        raise RuntimeError(
            "WIFI_BSSID or SENSING_BSSID is not set.  Export it in the shell or .env "
            "before starting (never commit it to the repo)."
        )

    interval = 1.0 / rate_hz
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    seq = 0
    errors = 0
    max_consecutive_errors = 50
    prev_rx_packets: int | None = None

    print(
        f"[wifi_rssi] polling {iface} -> {bus_host}:{bus_port} at {rate_hz} Hz",
        flush=True,
    )

    next_tick = time.monotonic()
    while True:
        dbm, rx_pkts = _read_station_info(iface, bssid)
        if dbm is not None and rx_pkts is not None:
            errors = 0
            if prev_rx_packets is not None and rx_pkts > prev_rx_packets:
                payload = _make_message(dbm, seq)
                sock.sendto(payload, (bus_host, bus_port))
                seq += 1
            prev_rx_packets = rx_pkts
        else:
            errors += 1
            if errors >= max_consecutive_errors:
                raise RuntimeError(
                    f"[wifi_rssi] {errors} consecutive read failures on {iface}. "
                    "Check that the board is associated to the sensing hotspot."
                )

        next_tick += interval
        sleep_for = next_tick - time.monotonic()
        if sleep_for > 0:
            time.sleep(sleep_for)
        else:
            # Fell behind; reset the tick so we don't spin trying to catch up.
            next_tick = time.monotonic()


def main() -> None:
    run()


if __name__ == "__main__":
    main()
