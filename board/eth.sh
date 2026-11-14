#!/usr/bin/env bash
# Gives the board's hub Ethernet 192.168.77.2/24 (CONTRACTS.md section 2): the board's end of the
# cable to the Pi. pi/eth.sh does the Pi's end (192.168.77.1). Run once, as root, on the board:
#
#   sudo bash board/eth.sh
#
# The profile comes up by itself at boot and outranks NetworkManager's own DHCP profile for the
# same port (nothing on the cable answers DHCP). The port is found, not named here, because a USB
# Ethernet adapter's name can carry its hardware address. With more than one wired port, set
# BOARD_ETH_IFACE in the repo's .env.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_DIR/.env}"
if [[ -f "$ENV_FILE" ]]; then
    # shellcheck source=/dev/null
    source "$ENV_FILE"
fi

NMCLI="${NMCLI:-nmcli}"
PING="${PING:-ping}"
CON_NAME="deadzone-eth"

# Wired ports NetworkManager knows, minus the USB gadget, containers and bridges.
wired_ports() {
    "$NMCLI" -t -f DEVICE,TYPE device |
        awk -F: '$2 == "ethernet" && $1 !~ /^(usb|rndis|veth|docker|br-)/ { print $1 }'
}

iface="${BOARD_ETH_IFACE:-}"
if [[ -z "$iface" ]]; then
    mapfile -t found < <(wired_ports)
    if [[ ${#found[@]} -eq 0 ]]; then
        echo "no wired port found: plug the Ethernet cable into the hub, or set BOARD_ETH_IFACE in .env" >&2
        exit 1
    fi
    if [[ ${#found[@]} -gt 1 ]]; then
        echo "${#found[@]} wired ports found: set BOARD_ETH_IFACE in .env to the hub's (see: nmcli device)" >&2
        exit 1
    fi
    iface="${found[0]}"
fi

"$NMCLI" connection delete "$CON_NAME" 2>/dev/null || true

"$NMCLI" connection add \
    type ethernet \
    ifname "$iface" \
    con-name "$CON_NAME" \
    autoconnect yes \
    -- \
    connection.autoconnect-priority 50 \
    ipv4.method manual \
    ipv4.addresses 192.168.77.2/24 \
    ipv4.never-default yes \
    ipv6.method disabled

if ! "$NMCLI" connection up "$CON_NAME"; then
    echo "saved, but not up: is the cable in? It comes up by itself once it is." >&2
    exit 1
fi
echo "hub Ethernet up at 192.168.77.2/24"

if "$PING" -c 1 -W 2 192.168.77.1 >/dev/null 2>&1; then
    echo "Pi 192.168.77.1 reachable"
else
    echo "Pi 192.168.77.1 not reachable yet: run pi/eth.sh on the Pi and check the cable" >&2
    exit 1
fi
