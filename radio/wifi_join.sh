#!/usr/bin/env bash
# Joins the UNO Q board to the Pi's 5 GHz sensing hotspot locked to the Pi's BSSID,
# with power saving disabled (CONTRACTS.md §2, AGENTS.md).
#
# Pi B (RADIO_NODE=pi5b in .env) joins the same way, plus one route: 192.168.77.0/24 via
# 10.42.0.1. The profile never takes the default route, and Pi B has no cable, so without it
# Pi B's readings to the board (192.168.77.2) have no way out. Pi A forwards them over its cable.
#
# Usage: sudo bash radio/wifi_join.sh
#
# Install everything the board needs first: once it's on the hotspot it has no internet.
# Needs SENSING_SSID, SENSING_PSK and SENSING_BSSID (or WIFI_BSSID) in the repo's .env. The BSSID
# is the Pi hotspot's address: on the Pi, after pi/ap.sh, the addr line of `/usr/sbin/iw dev <its 5 GHz
# interface> info`.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_DIR/.env}"

if [[ -f "$ENV_FILE" ]]; then
    # shellcheck source=/dev/null
    source "$ENV_FILE"
elif [[ -f ".env" ]]; then
    # shellcheck source=/dev/null
    source ".env"
fi

: "${SENSING_SSID:?set SENSING_SSID in .env}"
: "${SENSING_PSK:?set SENSING_PSK in .env}"
SENSING_BSSID="${SENSING_BSSID:-${WIFI_BSSID:-}}"
: "${SENSING_BSSID:?set SENSING_BSSID in .env}"
WIFI_IFACE="${WIFI_IFACE:-wlan0}"
NMCLI="${NMCLI:-nmcli}"
IW="${IW:-iw}"

CON_NAME="deadzone-sensing"

# Pi B reaches the board only through Pi A: route the cable's subnet via the hotspot's address.
ROUTES=()
if [[ "${RADIO_NODE:-}" == "pi5b" ]]; then
    ROUTES=(ipv4.routes "192.168.77.0/24 10.42.0.1")
fi

"$NMCLI" connection delete "$CON_NAME" 2>/dev/null || true

# autoconnect-priority 100: after a boot, wlan0 picks this over a saved phone hotspot.
# autoconnect-retries 0: keep trying for ever. NetworkManager's default gives up after 4 tries and
# then waits 5 minutes, so a Pi reboot would cost 5 minutes of Wi-Fi readings.
# never-default and ignore-auto-dns: only sensing goes over the hotspot.
"$NMCLI" connection add \
    type wifi \
    ifname "$WIFI_IFACE" \
    con-name "$CON_NAME" \
    autoconnect yes \
    ssid "$SENSING_SSID" \
    -- \
    connection.autoconnect-priority 100 \
    connection.autoconnect-retries 0 \
    802-11-wireless.band a \
    802-11-wireless.bssid "$SENSING_BSSID" \
    802-11-wireless.powersave 2 \
    wifi-sec.key-mgmt wpa-psk \
    wifi-sec.psk "$SENSING_PSK" \
    ipv4.never-default yes \
    ipv4.ignore-auto-dns yes \
    ${ROUTES[@]+"${ROUTES[@]}"} \
    ipv6.method disabled

"$NMCLI" connection up "$CON_NAME"

# Checks, printed without the BSSID so the output can go on an issue.
if "$IW" dev "$WIFI_IFACE" link 2>/dev/null | grep -qi "connected to ${SENSING_BSSID}"; then
    echo "joined: $WIFI_IFACE is on the Pi's hotspot"
else
    echo "NOT joined: $WIFI_IFACE isn't on the Pi's hotspot (check SENSING_BSSID, and that pi/ap.sh is up)" >&2
    exit 1
fi
"$IW" dev "$WIFI_IFACE" get power_save 2>/dev/null || true
if [[ ${#ROUTES[@]} -gt 0 ]]; then
    echo "route: 192.168.77.0/24 (the board) via Pi A's hotspot, 10.42.0.1"
fi
