# board/bench

Load numbers for the UNO Q before the demo. The camera teacher (App Lab), the radio readers,
the bus, the brain, the web server and llama-server all share its 4 Cortex-A53 cores. Run
from the repo root; on the board, use the services' venv (`PY=/opt/rs/venv/bin/python`).

## What to run, in order

1. **`python board/bench/bench_brain.py`** (any machine; 60 s after training). Trains the real
   model on sim sessions, then runs the brain's hot path at 10 Hz for 60 s through the modules
   on main (decode and windowing, forest predict, health, X-ray, advisor, state JSON) on a zone
   tour, then the tray at T1. Prints p50/p95/max ms per step and its CPU use. PC numbers are
   only relative. Options: `--trees`, `--depth`, `--hz`, `--seconds`.
2. **`bash board/bench/bench_llm.sh`** (board, llama-server up). Times one narrator sentence
   (the narrator's own prompt) while bench_brain.py runs: prompt tokens/s, generation tokens/s,
   wall time, PASS at 8 s or less, then the brain's numbers for the same stretch.
3. **`bash board/bench/load_all.sh`** (board, llama-server up; after part D of #95). Starts every
   section 9 entry point that isn't running, feeds the bus with `sim.send zone_tour --loop` and
   samples every 2 s for 5 minutes into `/tmp/rs-load-<time>/load.csv`: CPU % and RSS per
   process, temperature, clock and clock cap. Then a summary with throttling flags, the brain's
   step times and the narrator times. Post it on #95.
   - The brain is bench_brain.py (trained). `BRAIN=main` runs brain.main, untrained here.
   - The bench brain sends no events, so `llm_time.py` asks for a sentence every 8 s instead,
     the most the contract allows.
   - With sudo it also runs the BLE scan. No camera needed; a running App Lab app shows up too.

## Fine or trouble

Our margins, not measurements; only the narrator's 8 s comes from the contract.

| | Fine | Trouble |
|---|---|---|
| bench_brain `tick (all)` p95 | under 50 ms | over 80 ms (10 Hz leaves 100 ms) |
| bench_brain ticks over budget | 0 | more than 1% |
| bench_brain CPU | under 60% of one core | over 80% of one core |
| Narrator sentence | worst under 6 s | any over 8 s (the screen gets the template) |
| load_all system CPU p95 | under 80% of all cores | over 90% |
| load_all memory in use | under 3 GB | over 3.5 GB of 4 GB |
| load_all temperature, clock | under 75 C, clock at max | flagged: over 80 C, capped, or slow while busy |

## If it's trouble, change these first

1. **llama threads** (`narrator/llm.service`: `--threads 2 --threads-batch 2`, `CPUAffinity=2 3`).
   Brain late only while a sentence is written, sentences with time to spare: 1 thread on core
   3. Sentences over 8 s with CPU to spare: 3 threads on cores 1-3. Re-run bench_llm.sh.
2. **State rate** (try `bench_brain.py --hz 5`). predict, health, X-ray and the advisor run once
   per state message; windowing runs every 0.1 s regardless. Set in brain/main.py.
3. **Forest size** (try `bench_brain.py --trees 30 --depth 10`). predict is the biggest step in
   the PC run. Set `FOREST` in brain/train.py and re-check the zone score (proof/) first.

If load_all flags heat, add airflow before changing any setting: a hot board slows everything.
