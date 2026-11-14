#!/usr/bin/env bash
# Joins the UNO Q board to the Pi's 5 GHz sensing hotspot locked to the Pi's BSSID,
# with power saving disabled (CONTRACTS.md §2, AGENTS.md).
#
# Usage: sudo bash radio/wifi_join.sh
#
# Install everything the board needs first: once it's on the hotspot it has no internet.
# Needs SENSING_SSID, SENSING_PSK and SENSING_BSSID (or WIFI_BSSID) in the repo's .env. The BSSID
# is the Pi hotspot's address: on the Pi, after pi/ap.sh, the addr line of `iw dev <its 5 GHz
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
