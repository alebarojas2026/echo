#!/usr/bin/env bash
# Installs and starts the Pi's radio node from this checkout. One command, safe to run again:
#
#   sudo bash pi/install.sh
#
# The node uses only the Python standard library, so the venv its unit runs from
# (/opt/rs/venv, the same path as on the board) is made empty if it isn't there.
# Then board/deploy.sh installs radio-sight-radio-node (root, restarts 2 s after
# any failure) and starts it. Later code updates: pull, then
# `sudo systemctl restart radio-sight-radio-node`, or run this again.
#
# Settings, all optional: VENV (/opt/rs/venv), PYTHON3 (python3, what the venv is
# made from), and deploy.sh's own UNIT_DIR, SYSTEMCTL and SUDO.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${VENV:-/opt/rs/venv}"

if [ "$(id -u)" -ne 0 ] && [ -z "${SUDO+set}" ]; then
    echo "install: needs root to install a systemd unit; run: sudo bash pi/install.sh" >&2
    exit 1
fi

if [ ! -x "$VENV/bin/python" ]; then
    echo "install: making $VENV (empty: the node needs only the standard library)"
    "${PYTHON3:-python3}" -m venv "$VENV"
fi

ROLE=pi PYTHON="$VENV/bin/python" "$REPO_DIR/board/deploy.sh" --install
