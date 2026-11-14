#!/usr/bin/env bash
# Sets up the Pi's 5 GHz sensing hotspot via NetworkManager.
# Run as root on the Pi.  The board joins this network for sensing only.
# No secrets or BSSIDs are stored here; configure SSID and passphrase in
# /etc/deadzone.env (gitignored).
#
# Usage: sudo bash pi/ap.sh
set -euo pipefail

# Load local config (SSID and passphrase are not in the repo).
ENV_FILE="/etc/deadzone.env"
if [[ ! -f "$ENV_FILE" ]]; then
    cat >&2 <<'EOF'
Missing /etc/deadzone.env.  Create it with:
  SENSING_SSID=<your-ssid>
  SENSING_PSK=<your-passphrase>
  SENSING_IFACE=<your-5GHz-interface, e.g. wlan0>
EOF
    exit 1
fi
# shellcheck source=/dev/null
source "$ENV_FILE"

: "${SENSING_SSID:?set SENSING_SSID in /etc/deadzone.env}"
: "${SENSING_PSK:?set SENSING_PSK in /etc/deadzone.env}"
: "${SENSING_IFACE:?set SENSING_IFACE in /etc/deadzone.env}"

CON_NAME="deadzone-ap"

# Remove any stale profile with the same name.
nmcli connection delete "$CON_NAME" 2>/dev/null || true

nmcli connection add \
    type wifi \
    ifname "$SENSING_IFACE" \
    con-name "$CON_NAME" \
    autoconnect yes \
    ssid "$SENSING_SSID" \
    -- \
    wifi.mode ap \
    wifi.band a \
    wifi.channel 36 \
    wifi-sec.key-mgmt wpa-psk \
    wifi-sec.psk "$SENSING_PSK" \
    ipv4.method shared \
    ipv4.addresses 10.42.0.1/24 \
    ipv6.method disabled

nmcli connection up "$CON_NAME"
echo "Hotspot '$SENSING_SSID' up on $SENSING_IFACE (10.42.0.1/24, 5 GHz ch 36)"
