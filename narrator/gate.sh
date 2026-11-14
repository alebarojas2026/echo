#!/usr/bin/env bash
# Narrator gate: one sentence from the on-board model, end to end, in 8 s or less
# while the brain runs. On the UNO Q, from the repo root, with radio-sight-llm.service up:
#   bash narrator/gate.sh
# It warms the model once (the live narrator does the same when it starts), then
# times one fresh alert_on event from the event to the finished narration message.
set -u
cd "$(dirname "$0")/.."
PY=${PY:-/opt/rs/venv/bin/python}
LLM=${LLM:-http://127.0.0.1:8091}
LIMIT_MS=8000
LOG=/tmp/narrator-gate.log

fail() { echo "FAIL: $*"; exit 1; }

pgrep -f 'brain\.main' >/dev/null || fail "the brain is not running; start it first (python -m brain.main)"
curl -sf "$LLM/health" >/dev/null || fail "llama-server does not answer on $LLM/health (systemctl status radio-sight-llm)"

# Warm-up without the 8 s cap, so the timed sentence never queues behind it.
"$PY" -c 'import sys; from narrator import narrate as n; n.warm_up(n.LlamaServer(sys.argv[1], 120))' "$LLM"

t0=$(date +%s%3N)
msg=$("$PY" -m narrator.narrate --llm "$LLM" --once alert_on --info '{"zone": 4}' 2>"$LOG") \
    || fail "narrate.py crashed: $(tail -3 "$LOG")"
wall_ms=$(( $(date +%s%3N) - t0 ))
read -r source gen_ms text < <(printf '%s' "$msg" | "$PY" -c \
    'import json, sys; m = json.load(sys.stdin); print(m["source"], m["gen_ms"], m["text"])')

llama_pid=$(pgrep -x llama-server | head -1)
rss_mb=$(awk '/VmRSS/ {print int($2 / 1024)}' "/proc/${llama_pid:-0}/status" 2>/dev/null)
mhz=$(awk '{print int($1 / 1000)}' /sys/devices/system/cpu/cpu2/cpufreq/scaling_cur_freq 2>/dev/null)
temp_c=$(awk '{print int($1 / 1000)}' /sys/class/thermal/thermal_zone0/temp 2>/dev/null)

echo "sentence: $text"
echo "source:   $source"
echo "event to narration: ${gen_ms} ms (limit ${LIMIT_MS} ms), ${wall_ms} ms with python start-up"
echo "llama-server RSS ${rss_mb:-?} MB, cpu2 ${mhz:-?} MHz, ${temp_c:-?} C, load $(cut -d' ' -f1-3 /proc/loadavg)"
ps -o pid,psr,ni,pcpu,rss,args -p "$(pgrep -d, -f 'brain\.main|llama-server')" | cut -c1-120

[ "$source" = llm ] || fail "the template was used: $(tail -1 "$LOG")"
[ "$gen_ms" -le "$LIMIT_MS" ] || fail "${gen_ms} ms is over ${LIMIT_MS} ms"
echo PASS
