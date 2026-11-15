"""Run the question set through the board's model file on Modal CPUs (x86). Dev only.

    python -m lab.ask_bench.payloads --tag base                    # on the PC: the exact requests
    modal run lab/ask_bench/modal_bench.py --tag base              # answers to out/results-base.jsonl
    modal run lab/ask_bench/modal_bench.py --tag base --threads 4  # same requests, other thread count

Each container starts llama-server with narrator/llm.service's settings (2 threads, one slot,
ctx 1024, no host prompt cache) on the same GGUF, pinned by sha256, and sends the requests one at
a time, as agent/ask.py's Picker does. mlock is left out (containers may not allow it; it changes
no output). x86 timing is NOT the board's timing.
"""
import json
import subprocess
import time
import urllib.request
from pathlib import Path

import modal

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
LLAMA_TAG = "v1.0.0"   # narrator/README.md pins this release
GGUF = "qwen2.5-0.5b-instruct-q4_0.gguf"
GGUF_URL = ("https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/"
            "9217f5db79a29953eb74d5343926648285ec7e67/" + GGUF)
GGUF_SHA = "7671c0c304e6ce5a7fc577bcb12aba01e2c155cc2efd29b2213c95b18edaf6ed"
PORT = 8091

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git", "cmake", "build-essential", "curl")
    .run_commands(
        f"git clone --depth 1 --branch {LLAMA_TAG} https://github.com/ggml-org/llama.cpp /opt/llama.cpp",
        "cd /opt/llama.cpp && cmake -B build -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=OFF -DGGML_AVX2=ON "
        "-DGGML_FMA=ON -DGGML_F16C=ON -DBUILD_SHARED_LIBS=OFF -DLLAMA_CURL=OFF "
        "&& cmake --build build --config Release --target llama-server -j 8",
        "cd /opt/llama.cpp && git rev-parse HEAD > /opt/llama-commit.txt",
        f"mkdir -p /models && curl -sL --fail -o /models/{GGUF} {GGUF_URL} "
        f"&& echo '{GGUF_SHA}  /models/{GGUF}' | sha256sum -c",
    )
)
app = modal.App("ask-bench", image=image)


def _server(threads: int):
    args = ["/opt/llama.cpp/build/bin/llama-server", "--model", f"/models/{GGUF}", "--alias", "qwen2.5-0.5b-instruct-q4_0",
            "--host", "127.0.0.1", "--port", str(PORT), "--threads", str(threads), "--threads-batch", str(threads),
            "--parallel", "1", "--ctx-size", "1024", "--cache-ram", "0", "--no-webui"]
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=open("/tmp/llama.log", "w"))
    for _ in range(240):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2) as r:
                if json.load(r).get("status") == "ok":
                    return proc
        except Exception:
            pass
        if proc.poll() is not None:
            raise RuntimeError(open("/tmp/llama.log").read()[-3000:])
        time.sleep(0.5)
    raise RuntimeError("llama-server did not come up: " + open("/tmp/llama.log").read()[-3000:])


@app.function(cpu=2.0, memory=2048, timeout=2400, retries=1)
def run_shard(items: list, threads: int = 2) -> dict:
    proc = _server(threads)
    version = subprocess.run(["/opt/llama.cpp/build/bin/llama-server", "--version"], capture_output=True, text=True)
    cpu = next((l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name")), "?")
    out = []
    for it in items:
        t0 = time.perf_counter()
        rec = {"key": it["key"]}
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions", data=json.dumps(it["body"]).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                reply = json.load(r)
            rec["content"] = reply["choices"][0]["message"]["content"]
            rec["finish"] = reply["choices"][0].get("finish_reason")
            u = reply.get("usage") or {}
            rec["prompt_tokens"], rec["completion_tokens"] = u.get("prompt_tokens"), u.get("completion_tokens")
        except Exception as e:   # noqa: BLE001 - recorded, scored as a failure
            body = getattr(e, "read", lambda: b"")()
            rec["error"] = f"{type(e).__name__}: {e} {body[:300]!r}"
        rec["s"] = round(time.perf_counter() - t0, 4)
        out.append(rec)
    proc.terminate()
    return {"results": out, "version": (version.stdout + version.stderr).strip()[-300:],
            "commit": open("/opt/llama-commit.txt").read().strip(), "cpu": cpu, "threads": threads}


@app.local_entrypoint()
def main(tag: str = "base", threads: int = 2, shard: int = 400, rate_per_s: float = 1.0):
    items = [json.loads(l) for l in open(OUT / f"payloads-{tag}.jsonl", encoding="utf-8")]
    shards = [items[i:i + shard] for i in range(0, len(items), shard)]
    est_h = len(items) * rate_per_s / 3600
    print(f"{len(items)} requests in {len(shards)} containers; about {est_h:.2f} container-hours, "
          f"about ${est_h * 0.12 + 0.02 * len(shards):.2f} at 2 cores + 2 GiB")
    t0 = time.time()
    meta, n = None, 0
    suffix = "" if threads == 2 else f"-t{threads}"
    with open(OUT / f"results-{tag}{suffix}.jsonl", "w", encoding="utf-8") as f:
        for res in run_shard.map(shards, kwargs={"threads": threads}):
            meta = meta or {k: v for k, v in res.items() if k != "results"}
            for r in res["results"]:
                f.write(json.dumps(r) + "\n")
                n += 1
    meta["wall_s"] = round(time.time() - t0)
    meta["requests"] = n
    (OUT / f"meta-{tag}{suffix}.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta, indent=1))
