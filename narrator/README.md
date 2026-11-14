# narrator

One plain sentence on the screen for each brain event, written by a small language model on
the UNO Q. It runs on the board only.

```
python -m narrator.narrate                                   # live (its unit lives in board/units/)
python -m narrator.narrate --once enter --info '{"zone": 2}'  # one sentence, printed, nothing sent
```

It reads events from the brain (ws://127.0.0.1:8765/ws), asks llama-server on 127.0.0.1:8091
for one sentence and sends a `narration` message to the bus (UDP 127.0.0.1:5600). At most one
sentence every 8 s, only for events up to 3 s old, at most 16 words. The 8 s gap runs from when a
sentence starts being written, so a 6 s model still speaks every 8 s. While it writes or waits,
it keeps the most important event, not the newest (alert, check-in and camera-off come first), and
it never narrates `router_moved` or `advice`, which the screen already shows. When the model is slow
(over 8 s), down, or says a banned word, the event's template sentence goes out instead, with
`"source": "template"`.

On the board, llama-server takes a while to load the model after boot and answers "connection
refused" or HTTP 503 until then; those events get their template sentence. The narrator warms the
model's prompt cache in the background and keeps retrying until the server answers. It warms it
again after a failed model call (the server may have restarted) and after each recap, whose prompt
takes the server's one cache slot. A model call that is still waiting for a free worker when its
8 s run out is dropped, never sent. A `reset` drops any event still waiting, so the recap is the
next thing said. The rules are in CONTRACTS.md sections 4-6; the banned words and the
templates are at the top of `narrate.py`. Besides the standard library it needs only
`websockets`, which is in /opt/rs/venv.

## Tests (any machine, no model, no network)

```
pip install -r narrator/requirements.txt
python -m pytest narrator
```

## The model

Qwen2.5-0.5B-Instruct, 4-bit (Q4_0), Apache-2.0, from Qwen's own GGUF repo.

| | |
|---|---|
| Repo | https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF, revision `9217f5db79a29953eb74d5343926648285ec7e67` |
| File | `qwen2.5-0.5b-instruct-q4_0.gguf`, 428,730,208 bytes |
| sha256 | `7671c0c304e6ce5a7fc577bcb12aba01e2c155cc2efd29b2213c95b18edaf6ed` |

Why this one: the A53 cores have no dot-product instructions, so speed comes down to how much
work each token costs. Qwen2.5-0.5B is a plain transformer, so llama-server keeps the fixed
start of the prompt cached and each event adds only about 30 new tokens. Qwen3.5-0.8B costs
more per token (more weights, and a 248k-token vocabulary against 152k), and its
linear-attention layers carry a running state, so llama-server can't reuse just the shared
start of the prompt the same way.

## 1. Build llama.cpp on the UNO Q

Debian 13 has no llama.cpp package, so build it from source, CPU only, pinned to release
v1.0.0. Do this while the board has internet (the Pi's tether) and nothing is recording.

```
sudo apt-get update
sudo apt-get install -y git cmake build-essential curl
sudo mkdir -p /opt/rs/llama.cpp /opt/rs/models
sudo chown arduino: /opt/rs/llama.cpp /opt/rs/models
git clone --depth 1 --branch v1.0.0 https://github.com/ggml-org/llama.cpp /opt/rs/llama.cpp
cd /opt/rs/llama.cpp
cmake -B build -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON -DBUILD_SHARED_LIBS=OFF
cmake --build build --config Release --target llama-server -j 2
build/bin/llama-server --version
```

- `GGML_NATIVE=ON` compiles for this CPU (Cortex-A53, Armv8.0 with NEON). Build it on the board;
  don't copy a binary from another machine.
- `BUILD_SHARED_LIBS=OFF` gives one self-contained binary, the path `radio-sight-llm.service` runs.
- `-j 2` because some llama.cpp files need a lot of memory to compile; four jobs at once can run
  the 4 GB board out of memory. Expect the build to take a while.
- "OpenSSL not found, HTTPS support disabled" during `cmake` is fine: the model is downloaded
  with curl below, not by llama-server.

## 2. Download the model

```
curl -L --fail -o /opt/rs/models/qwen2.5-0.5b-instruct-q4_0.gguf \
  https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/9217f5db79a29953eb74d5343926648285ec7e67/qwen2.5-0.5b-instruct-q4_0.gguf
echo "7671c0c304e6ce5a7fc577bcb12aba01e2c155cc2efd29b2213c95b18edaf6ed  /opt/rs/models/qwen2.5-0.5b-instruct-q4_0.gguf" | sha256sum -c
```

## 3. Run it as a service

`narrator/llm.service` is installed as `radio-sight-llm.service` along with the other units
(board/units/README.md). From the repo root on the board:

```
sudo board/deploy.sh --install --no-pi   # or without --no-pi once the Pi is up
curl -s http://127.0.0.1:8091/health     # {"status":"ok"} once the model is loaded
journalctl -u radio-sight-llm -n 40      # model load, threads, buffer sizes
```

The unit runs `--threads 2 --threads-batch 2 --parallel 1 --ctx-size 1024` on 127.0.0.1:8091,
with `CPUAffinity=2 3` and `Nice=10`.

## 4. Gate

With radio-sight-llm.service up and the brain running:

```
bash narrator/gate.sh
```

It warms the model once (the live narrator does the same when it starts), runs one fresh
`alert_on` event through the narrator and prints the sentence, the time from event to
narration, llama-server's memory, the CPU clock and temperature, and the cores each process
sits on. Then PASS (a model sentence in 8 s or less) or FAIL with the reason. It uses
/opt/rs/venv/bin/python; set `PY=...` to use another. Post the output on issue #53 and copy
the numbers into the budget below.

## Budget

`__` = not measured yet. gate.sh prints the real numbers.

| | |
|---|---|
| CPU | llama-server: 2 threads on cores 2-3, nice 10. Busy only while it writes a sentence (at most one every 8 s), idle otherwise. Cores 0-1 stay free for the radio readers and the brain. |
| RAM | Model 429 MB, locked in RAM (`--load-mode mmap+mlock`, so a busy disk can't page it out), a 1024-token KV cache of about 12 MB, and llama.cpp's working buffers. `MemoryMax=1G` caps the service. Measured RSS: __ MB. |
| Time | Event to narration: __ ms. Limit 8000 ms. |
| Disk | The 429 MB model plus the llama.cpp source and build in /opt/rs/llama.cpp. |

## End-of-demo recap

When the screen sends `reset` between judges, the narrator turns the brain's events since the
last reset into a short list of facts with times and zone names, and the on-board model writes a
recap of at most 3 sentences and 45 words (`narrator/recap.py`). It goes to the bus as a
`narration` with `event_kind` `recap`, with `gen_ms` recorded as for any sentence. A recap built
directly from the same facts is sent instead when the model is slow (over 25 s), unreachable, too
long, adds a number that is not in the facts, or uses a banned word. Signal levels appear only when
an `advice_result` event carried them. A reset with nothing to tell sends nothing.

To check the recap on the board, with radio-sight-llm up:

```
/opt/rs/venv/bin/python -m narrator.recap
```

It writes one recap of a sample demo (a tour, the alert, a wave, the camera unplugged, walking out)
and prints the narration and how long it took. Nothing is sent. Exit 1 means the template was used,
with the reason. Recap time: __ ms. Limit 25000 ms.

The recap keeps the 8 s spacing: it goes out no sooner than 8 s after the last sentence, and the
next judge's first sentence waits 8 s after it. The schema allows `recap` and 45 words (#280).
