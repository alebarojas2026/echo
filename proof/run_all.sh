#!/bin/sh
set -eu
TASK_REPO=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$TASK_REPO"
exec "${PYTHON:-python3}" -m proof.run_all "$@"
