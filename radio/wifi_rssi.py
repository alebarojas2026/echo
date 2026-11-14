"""Wi-Fi RSSI reader for the UNO Q (north node).

Reads the received-signal-strength of the pi5>unoq:wifi link by polling
``iw dev <iface> station get <bssid>`` at a target rate and publishing
contract-v2 ``rssi`` messages to the bus.

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
BSSID: str = os.environ.get("WIFI_BSSID", "")  # required at runtime
BUS_HOST: str = os.environ.get("BUS_HOST", "127.0.0.1")
BUS_PORT: int = int(os.environ.get("BUS_PORT", "5600"))
RATE_HZ: float = float(os.environ.get("RATE_HZ", "25"))

LINK_ID = "pi5>unoq:wifi"
TX = "pi5"
RX = "unoq"
KIND = "wifi"

# iw reports signal in a line like:
#   signal:                 -62 dBm
_SIGNAL_RE = re.compile(r"signal:\s+(-?\d+)\s+dBm")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_rssi_dbm(iface: str, bssid: str) -> int | None:
    """Return the current RSSI in dBm, or None if unavailable."""
    try:
        out = subprocess.check_output(
            ["iw", "dev", iface, "station", "get", bssid],
            stderr=subprocess.DEVNULL,
            timeout=0.5,
        ).decode()
    except Exception:
        return None
    m = _SIGNAL_RE.search(out)
    return int(m.group(1)) if m else None


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
            "WIFI_BSSID is not set.  Export it in the shell before starting "
            "(never commit it to the repo)."
        )

    interval = 1.0 / rate_hz
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    seq = 0
    errors = 0
    max_consecutive_errors = 50

    print(
        f"[wifi_rssi] polling {iface} station {bssid[:5]}… "
        f"-> {bus_host}:{bus_port} at {rate_hz} Hz",
        flush=True,
    )

    next_tick = time.monotonic()
    while True:
        dbm = _read_rssi_dbm(iface, bssid)
        if dbm is not None:
            payload = _make_message(dbm, seq)
            sock.sendto(payload, (bus_host, bus_port))
            seq += 1
            errors = 0
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
