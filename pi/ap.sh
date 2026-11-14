#!/usr/bin/env bash
# Sets up the Pi's 5 GHz sensing hotspot via NetworkManager.
# Run as root on the Pi.  The board joins this network for sensing only.
# No secrets or BSSIDs are stored here; configure SSID and passphrase in
# .env at the repo root (gitignored).
#
# Usage: sudo bash pi/ap.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -f "$REPO_DIR/.env" ]]; then
    # shellcheck source=/dev/null
    source "$REPO_DIR/.env"
elif [[ -f ".env" ]]; then
    # shellcheck source=/dev/null
    source ".env"
elif [[ -f "/etc/deadzone.env" ]]; then
    # shellcheck source=/dev/null
    source "/etc/deadzone.env"
fi

: "${SENSING_SSID:?set SENSING_SSID in .env}"
: "${SENSING_PSK:?set SENSING_PSK in .env}"
# The Pi 5's built-in Wi-Fi. Set SENSING_IFACE in .env for anything else.
SENSING_IFACE="${SENSING_IFACE:-wlan0}"

# 1. Set regulatory domain to US and verify
iw reg set US
if ! iw reg get | grep -q "country US"; then
    echo "Error: regulatory domain is not country US" >&2
    exit 1
fi

CON_NAME="deadzone-ap"

# Remove any stale profile with the same name.
nmcli connection delete "$CON_NAME" 2>/dev/null || true

# 2. Force WPA2, channel 36, and 20 MHz channel width. Priority 100 beats any
#    saved client profile on the same interface (the phone hotspot used for
#    installs sits at 0), so after a reboot the Pi starts this hotspot instead
#    of joining the phone.
nmcli connection add \
    type wifi \
    ifname "$SENSING_IFACE" \
    con-name "$CON_NAME" \
    autoconnect yes \
    ssid "$SENSING_SSID" \
    -- \
    connection.autoconnect-priority 100 \
    wifi.mode ap \
    wifi.band a \
    wifi.channel 36 \
    802-11-wireless.channel-width 20mhz \
    wifi-sec.key-mgmt wpa-psk \
    wifi-sec.proto rsn \
    wifi-sec.pairwise ccmp \
    wifi-sec.group ccmp \
    wifi-sec.psk "$SENSING_PSK" \
    ipv4.method shared \
    ipv4.addresses 10.42.0.1/24 \
    ipv6.method disabled

nmcli connection up "$CON_NAME"

# 3. Check dmesg for brcmfmac errors
if dmesg | tail -n 100 | grep -Ei "brcmfmac.*(error|failed)"; then
    echo "Error: brcmfmac error found in dmesg after starting hotspot" >&2
    exit 1
fi

echo "Hotspot '$SENSING_SSID' up on $SENSING_IFACE (10.42.0.1/24, 5 GHz ch 36, 20 MHz, WPA2)"
