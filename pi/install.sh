#!/usr/bin/env bash
# Installs and starts the Pi's radio node from this checkout. One command, safe to run again:
#
#   sudo bash pi/install.sh                # Pi A (pi5): the router, beacon S
#   sudo bash pi/install.sh --node pi5b    # Pi B (pi5b): the second Pi of the desk layout, beacon B
#
# The node uses only the Python standard library, so the venv its unit runs from
# (/opt/rs/venv, the same path as on the board) is made empty if it isn't there.
# Then board/deploy.sh installs radio-sight-radio-node (root, restarts 2 s after
# any failure) and starts it. Later code updates: pull, then
# `sudo systemctl restart radio-sight-radio-node`, or run this again.
#
# Pi B has no cable and no hotspot of its own. --node pi5b also:
#   - writes RADIO_NODE, WIFI_LINK and BUS_HOST into the repo's .env when they're missing;
#   - turns off this Pi's own hotspot (deadzone-ap), if it has one;
#   - installs the Wi-Fi reader too (ROLE=pib), for the pi5>pi5b:wifi link;
#   - joins Pi A's hotspot with radio/wifi_join.sh (SENSING_SSID, SENSING_PSK and SENSING_BSSID
#     in .env, the same three lines as on the board), unless it's joined already;
#   - waits for the node's first status line and ends with `python3 -m pi.check --node pi5b`,
#     whose last line is "all ok" or how many checks failed (and the exit code says the same).
#
# Settings, all optional: VENV (/opt/rs/venv), PYTHON3 (python3, what the venv is
# made from), WIFI_IFACE (wlan0), NMCLI (nmcli), IP (ip), WIFI_JOIN (radio/wifi_join.sh),
# CHECK_WAIT_S (12, Pi B only), and
# deploy.sh's own UNIT_DIR, SYSTEMCTL and SUDO.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${VENV:-/opt/rs/venv}"
ENV_FILE="$REPO_DIR/.env"
NMCLI="${NMCLI:-nmcli}"
WIFI_IFACE="${WIFI_IFACE:-wlan0}"

NODE=pi5
while [ $# -gt 0 ]; do
    case $1 in
        --node) NODE=${2:-}; shift 2 || { echo "install: --node needs pi5 or pi5b" >&2; exit 2; } ;;
        --node=*) NODE=${1#--node=}; shift ;;
        *) echo "usage: sudo bash pi/install.sh [--node pi5|pi5b]" >&2; exit 2 ;;
    esac
done
case $NODE in
    pi5) ROLE=pi ;;
    pi5b) ROLE=pib ;;
    *) echo "install: --node is pi5 (Pi A) or pi5b (Pi B), not '$NODE'" >&2; exit 2 ;;
esac

if [ "$(id -u)" -ne 0 ] && [ -z "${SUDO+set}" ]; then
    echo "install: needs root to install a systemd unit; run: sudo bash pi/install.sh${NODE:+ --node $NODE}" >&2
    exit 1
fi

# KEY=VALUE into .env unless KEY is already there. The value is single-quoted: .env is also
# sourced by bash (radio/wifi_join.sh), where an unquoted pi5>pi5b:wifi would be a redirect.
env_default() {
    local key=$1 value=$2
    if [ -f "$ENV_FILE" ] && grep -Eq "^[[:space:]]*(export[[:space:]]+)?$key=" "$ENV_FILE"; then
        echo "install: .env already sets $key; leaving it"
        return
    fi
    [ ! -s "$ENV_FILE" ] || [ -z "$(tail -c 1 "$ENV_FILE")" ] || echo >> "$ENV_FILE"
    printf "%s='%s'\n" "$key" "$value" >> "$ENV_FILE"
    echo "install: .env: $key=$value"
}

if [ "$NODE" = pi5b ]; then
    env_default RADIO_NODE pi5b
    env_default WIFI_LINK 'pi5>pi5b:wifi'
    env_default BUS_HOST 192.168.77.2
    # Pi B listens on Pi A's hotspot, so its own must be off (an SD card copied from Pi A has it).
    if "$NMCLI" -t -f NAME connection show 2>/dev/null | grep -qx deadzone-ap; then
        "$NMCLI" connection modify deadzone-ap connection.autoconnect no
        "$NMCLI" connection down deadzone-ap >/dev/null 2>&1 || true
        echo "install: this Pi's own hotspot (deadzone-ap) is off and won't come back at boot"
    fi
fi

if [ ! -x "$VENV/bin/python" ]; then
    echo "install: making $VENV (empty: the node needs only the standard library)"
    "${PYTHON3:-python3}" -m venv "$VENV"
fi

ROLE=$ROLE PYTHON="$VENV/bin/python" "$REPO_DIR/board/deploy.sh" --install

[ "$NODE" = pi5b ] || exit 0

addr=$("${IP:-ip}" -4 -o addr show dev "$WIFI_IFACE" 2>/dev/null || true)
if grep -q "inet 10\.42\.0\." <<< "$addr" && ! grep -q "inet 10\.42\.0\.1/" <<< "$addr"; then
    echo "install: $WIFI_IFACE is already on Pi A's hotspot"
else
    bash "${WIFI_JOIN:-$REPO_DIR/radio/wifi_join.sh}"
fi

echo "install: waiting ${CHECK_WAIT_S:-12} s for the node's first status line, then checking"
sleep "${CHECK_WAIT_S:-12}"
cd "$REPO_DIR"
"${PYTHON3:-python3}" -m pi.check --node pi5b
