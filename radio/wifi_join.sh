#!/usr/bin/env bash
# Joins the UNO Q board to the Pi's 5 GHz sensing hotspot locked to the Pi's BSSID,
# with power saving disabled (CONTRACTS.md §2, AGENTS.md).
#
# Usage: sudo bash radio/wifi_join.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -f "$REPO_DIR/.env" ]]; then
    # shellcheck source=/dev/null
    source "$REPO_DIR/.env"
elif [[ -f ".env" ]]; then
    # shellcheck source=/dev/null
    source ".env"
fi

: "${SENSING_SSID:?set SENSING_SSID in .env}"
: "${SENSING_PSK:?set SENSING_PSK in .env}"
SENSING_BSSID="${SENSING_BSSID:-${WIFI_BSSID:-}}"
: "${SENSING_BSSID:?set SENSING_BSSID in .env}"
WIFI_IFACE="${WIFI_IFACE:-wlan0}"

CON_NAME="deadzone-sensing"

nmcli connection delete "$CON_NAME" 2>/dev/null || true

nmcli connection add \
    type wifi \
    ifname "$WIFI_IFACE" \
    con-name "$CON_NAME" \
    autoconnect yes \
    ssid "$SENSING_SSID" \
    -- \
    802-11-wireless.bssid "$SENSING_BSSID" \
    802-11-wireless.powersave 2 \
    wifi-sec.key-mgmt wpa-psk \
    wifi-sec.psk "$SENSING_PSK"

nmcli connection up "$CON_NAME"
echo "$WIFI_IFACE"
