#!/usr/bin/env bash
# Everything at once on the UNO Q with the sim feed, sampled every 2 s for 5 minutes.
# On the board, from the repo root, with llama-server up (radio-sight-llm.service):
#   bash board/bench/load_all.sh        # with sudo it also starts the root-only BLE scan
# Starts each CONTRACTS.md section 9 board entry point that isn't running yet, feeds the bus
# with sim.send, samples into $OUT/load.csv and stops only what it started (board/bench/README.md).
# Settings: SECS (300), EVERY (2), PY, LLM, OUT, BRAIN=bench (bench_brain.py) or main.
set -u
cd "$(dirname "$0")/../.."
SECS=${SECS:-300}
EVERY=${EVERY:-2}
PY=${PY:-$(ls .venv/bin/python /opt/rs/venv/bin/python 2>/dev/null | head -1)}
PY=${PY:-python3}
LLM=${LLM:-http://127.0.0.1:8091}
OUT=${OUT:-/tmp/rs-load-$(date +%H%M%S)}
BRAIN=${BRAIN:-bench}
mkdir -p "$OUT" && started=()

say() { echo "load_all: $*"; }
fail() { echo "FAIL: $*"; exit 1; }
trap '[ ${#started[@]} -gt 0 ] && kill -TERM "${started[@]}" 2>/dev/null; wait' EXIT
trap 'exit 130' INT TERM

# start NAME PATTERN CMD...: run CMD in the background unless PATTERN is already running.
start() {
    local name=$1 pattern=$2 pid; shift 2
    pid=$(pgrep -f -- "$pattern" | head -1)
    if [ -n "$pid" ]; then say "$name already running (pid $pid), sampling it as it is"; return; fi
    "$@" >"$OUT/$name.log" 2>&1 &
    started+=($!)
    say "$name started (pid $!), log in $OUT/$name.log"
}

"$PY" -c 'import numpy, sklearn' 2>/dev/null || fail "$PY has no numpy or scikit-learn; set PY=..."
curl -sf "$LLM/health" >/dev/null || fail "no llama-server on $LLM: sudo systemctl start radio-sight-llm"
case $BRAIN in bench | main) ;; *) fail "BRAIN is bench or main, not $BRAIN" ;; esac

start bus "-m bus" "$PY" -m bus
if [ -f radio/wifi_rssi.py ]; then start wifi_rssi radio.wifi_rssi "$PY" -m radio.wifi_rssi
else say "radio/wifi_rssi.py is not on this checkout, skipped"; fi
if [ ! -f radio/hci_scan.py ]; then say "radio/hci_scan.py is not on this checkout, skipped"
elif [ "$(id -u)" -ne 0 ]; then say "hci_scan needs root, skipped"
else start hci_scan radio.hci_scan "$PY" -m radio.hci_scan --node unoq; fi
start camwatch teacher.camwatch "$PY" -m teacher.camwatch
if [ "$BRAIN" = main ]; then start brain brain.main "$PY" -m brain.main
else start bench_brain bench_brain "$PY" board/bench/bench_brain.py --seconds $((SECS + 60)); fi
start serve board/serve.py "$PY" board/serve.py
start narrate narrator.narrate "$PY" -m narrator.narrate
start sim_send sim.send "$PY" -m sim.send zone_tour --loop
if [ "$BRAIN" = bench ]; then
    for _ in $(seq 300); do   # sample once it has trained and is in its 10 Hz loop
        grep -qs '^running' "$OUT/bench_brain.log" && break
        sleep 1
    done
    grep -qs '^running' "$OUT/bench_brain.log" || fail "bench_brain didn't start: $(tail -3 "$OUT/bench_brain.log")"
    # The bench brain sends no events, so the narrator stays quiet. Ask for its worst case
    # instead: one sentence every 8 s, the contract's limit.
    start llm_time llm_time.py "$PY" board/bench/llm_time.py --llm "$LLM" --every 8 --seconds $((SECS - 10))
fi
sleep 5
say "sampling every $EVERY s for $SECS s into $OUT/load.csv"
"$PY" board/bench/sample.py --seconds "$SECS" --every "$EVERY" --csv "$OUT/load.csv" | tee "$OUT/summary.txt"

pkill -TERM -f bench_brain && sleep 1   # it prints its step times on the way out
[ -f "$OUT/bench_brain.log" ] && { echo; echo "brain:"; tail -n 10 "$OUT/bench_brain.log"; }
[ -f "$OUT/llm_time.log" ] && { echo; echo "narrator:"; tail -n 1 "$OUT/llm_time.log"; }
say "CSV and logs in $OUT; logs with errors: $(grep -lE 'Traceback|Error' "$OUT"/*.log | paste -sd ' ')"
