#!/usr/bin/env bash
# Configures the Pi's Ethernet port with a static address (192.168.77.1/24)
# and brings the link up.  Run as root on the Pi.
#
# The board's hub sits at 192.168.77.2.  This cable carries all traffic
# except the sensing Wi-Fi link.
#
# Usage: sudo bash pi/eth.sh
set -euo pipefail

ENV_FILE="/etc/deadzone.env"
if [[ ! -f "$ENV_FILE" ]]; then
    cat >&2 <<'EOF'
Missing /etc/deadzone.env.  Create it with:
  ETH_IFACE=<Ethernet interface name, e.g. eth0>
EOF
    exit 1
fi
# shellcheck source=/dev/null
source "$ENV_FILE"

: "${ETH_IFACE:?set ETH_IFACE in /etc/deadzone.env}"

CON_NAME="deadzone-eth"

nmcli connection delete "$CON_NAME" 2>/dev/null || true

nmcli connection add \
    type ethernet \
    ifname "$ETH_IFACE" \
    con-name "$CON_NAME" \
    autoconnect yes \
    -- \
    ipv4.method manual \
    ipv4.addresses 192.168.77.1/24 \
    ipv4.gateway "" \
    ipv4.dns "" \
    ipv6.method disabled

nmcli connection up "$CON_NAME"
echo "Ethernet $ETH_IFACE up at 192.168.77.1/24"

# Quick reachability check to board hub (may not be connected yet).
if ping -c 1 -W 2 192.168.77.2 &>/dev/null; then
    echo "Board hub 192.168.77.2 reachable."
else
    echo "Board hub not yet reachable (plug the Ethernet cable if not done)."
fi
