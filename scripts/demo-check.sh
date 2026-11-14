#!/bin/sh
set -u
exec python3 "$(dirname "$0")/demo_check.py" "$@"
