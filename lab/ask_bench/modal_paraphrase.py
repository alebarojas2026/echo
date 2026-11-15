"""Paraphrases from a larger open model, for variety the templates lack. Dev only.

    modal run lab/ask_bench/modal_paraphrase.py --n 260

It runs Qwen2.5-7B-Instruct (Q4_K_M GGUF) under the same llama.cpp build as the bench, on 8 CPU
containers. (An L4 run with a 14B model was tried first; no GPU was scheduled in 40 minutes.)

Seeds are template questions (dev and test). Each paraphrase keeps its seed's known right pick
and is kept only if it still names the same time (its digits or number words) and the same side.
They get split "para". The hand-written questions are never paraphrased.
"""
import json
import random
import re
from pathlib import Path

import modal

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
MODEL = "Qwen2.5-7B-Instruct-Q4_K_M.gguf"
MODEL_URL = "https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/" + MODEL
MODEL_SHA = "65b8fcd92af6b4fefa935c625d1ac27ea29dcb6ee14589c55a8f115ceaaa1423"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git", "cmake", "build-essential", "curl")
    .run_commands(
        "git clone --depth 1 --branch v1.0.0 https://github.com/ggml-org/llama.cpp /opt/llama.cpp",
        "cd /opt/llama.cpp && cmake -B build -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=OFF -DGGML_AVX2=ON "
        "-DGGML_FMA=ON -DGGML_F16C=ON -DBUILD_SHARED_LIBS=OFF -DLLAMA_CURL=OFF "
        "&& cmake --build build --config Release --target llama-server -j 8",
        f"mkdir -p /models && curl -sL --fail -o /models/{MODEL} {MODEL_URL} && echo '{MODEL_SHA}  /models/{MODEL}' | sha256sum -c",
    )
)
app = modal.App("ask-bench-para", image=image)

PROMPT = ("People at a hackathon demo desk type questions into a text box on a room sensor's screen. "
          "Rewrite the question below the way 4 different visitors might type it. One per line, no numbering, "
          "no quotes: one short and casual, one with a small typo, one longer and polite, one from someone whose "
          "English is a second language. Keep the exact meaning. Keep any time (like 'since 2' or 'last hour') "
          "and any side (left or right) exactly as asked, and do not add a time or a side that is not there.\n"
          "Question: {q}")


@app.function(cpu=8.0, memory=8192, timeout=2400)
def paraphrase(seeds: list) -> dict:
    import subprocess
    import time
    import urllib.request
    proc = subprocess.Popen(["/opt/llama.cpp/build/bin/llama-server", "--model", f"/models/{MODEL}", "--port", "8092",
                             "--threads", "8", "--ctx-size", "2048", "--parallel", "1", "--no-webui"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(600):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8092/health", timeout=2) as r:
                if json.load(r).get("status") == "ok":
                    break
        except Exception:
            time.sleep(1)
    texts = []
    for k, s in enumerate(seeds):
        body = {"messages": [{"role": "user", "content": PROMPT.format(q=s)}], "max_tokens": 160,
                "temperature": 0.9, "top_p": 0.95, "seed": 3 + k}
        req = urllib.request.Request("http://127.0.0.1:8092/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                texts.append(json.load(r)["choices"][0]["message"]["content"])
        except Exception as e:   # noqa: BLE001 - a lost seed just gives no paraphrases
            texts.append("")
    proc.terminate()
    return {"version": "llama.cpp v1.0.0", "texts": texts}


NUMWORDS = "one two three four five six seven eight nine ten eleven twelve fifteen twenty thirty forty fifty sixty".split()


def keeps(seed: str, para: str) -> bool:
    s, p = seed.lower(), para.lower()
    for d in re.findall(r"\d+", s):
        if d not in p and NUMWORDS[int(d) - 1 if int(d) <= 12 else 0] not in p:
            return False
    for w in NUMWORDS + ["noon", "today", "hour", "half", "quarter", "day", "just now", "right now"]:
        if re.search(rf"\b{w}\b", s) and not re.search(rf"\b{w}\b", p):
            return False
    for side in ("left", "right"):
        if (side in s) != (side in p) and not (side == "right" and "right now" in s):
            return False
    return 3 <= len(p) <= 200


@app.local_entrypoint()
def main(n: int = 260, seed: int = 11):
    rows = [json.loads(l) for l in open(OUT / "questions.jsonl", encoding="utf-8")]
    pool = [r for r in rows if r["split"] in ("dev", "test") and r["cat"] != "half"]
    rng = random.Random(seed)
    by_tool = {}
    for r in pool:
        by_tool.setdefault(r["tool"], []).append(r)
    picked = []
    for tool, rs in by_tool.items():   # even-ish over tools, so the small tools get variety too
        picked += rng.sample(rs, min(len(rs), max(20, n // len(by_tool))))
    print(f"{len(picked)} seeds on 8 CPU containers; about $0.60")
    chunks = [picked[k::8] for k in range(8)]
    res = {"texts": [None] * len(picked)}
    for k, out in enumerate(paraphrase.map([[r["q"] for r in c] for c in chunks])):
        res["version"] = out["version"]
        for n, text in enumerate(out["texts"]):
            res["texts"][k + 8 * n] = text
    out, seen, dropped = [], {r["q"].lower() for r in rows}, 0
    for r, text in zip(picked, res["texts"]):
        for line in text.splitlines():
            p = line.strip().strip('"').strip()
            p = re.sub(r"^(\d+[.)]|[-*])\s*", "", p)
            if not p or p.lower() in seen:
                continue
            if not keeps(r["q"], p):
                dropped += 1
                continue
            seen.add(p.lower())
            out.append({**r, "id": f"p{len(out):05d}", "q": p, "split": "para", "seed": r["id"]})
    with open(OUT / "paraphrases.jsonl", "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r) + "\n")
    print(f"{res['version']}, {MODEL}: kept {len(out)}, dropped {dropped}")
