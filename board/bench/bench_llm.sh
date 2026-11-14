#!/usr/bin/env bash
# One narrator sentence through llama-server, timed while bench_brain.py keeps the brain busy.
# On the UNO Q, from the repo root, with llama-server up on 127.0.0.1:8091:
#   bash board/bench/bench_llm.sh
# Prints prompt and generation tokens/s, wall time, PASS at 8 s or less, then the brain's times.
set -u
cd "$(dirname "$0")/../.."
PY=${PY:-$(ls .venv/bin/python /opt/rs/venv/bin/python 2>/dev/null | head -1)}
PY=${PY:-python3}
LLM=${LLM:-http://127.0.0.1:8091}
LOG=$(mktemp)
fail() { echo "FAIL: $*"; exit 1; }

curl -sf "$LLM/health" >/dev/null || fail "no llama-server on $LLM: sudo systemctl start radio-sight-llm"
"$PY" board/bench/bench_brain.py --seconds 300 >"$LOG" 2>&1 &
brain=$!
trap 'kill "$brain" 2>/dev/null; rm -f "$LOG"' EXIT
for _ in $(seq 300); do   # it trains first; wait for its 10 Hz loop
    grep -q '^running' "$LOG" && break
    kill -0 "$brain" 2>/dev/null || fail "bench_brain.py stopped: $(tail -3 "$LOG")"
    sleep 1
done
grep -q '^running' "$LOG" || fail "bench_brain.py didn't reach its loop in 300 s"
sleep 5
"$PY" board/bench/llm_time.py --llm "$LLM"
status=$?
kill -TERM "$brain" && wait "$brain"
echo; echo "brain while the sentence ran:"; tail -n 10 "$LOG"
exit "$status"
