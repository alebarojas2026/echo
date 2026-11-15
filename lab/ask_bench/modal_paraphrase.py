"""Paraphrases from a larger open model on one Modal L4, for variety the templates lack. Dev only.

    modal run lab/ask_bench/modal_paraphrase.py --n 260

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
MODEL = "Qwen/Qwen2.5-14B-Instruct-AWQ"

image = modal.Image.debian_slim(python_version="3.12").uv_pip_install("vllm", "huggingface_hub[hf_transfer]") \
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
app = modal.App("ask-bench-para", image=image)

PROMPT = ("People at a hackathon demo desk type questions into a text box on a room sensor's screen. "
          "Rewrite the question below the way 4 different visitors might type it. One per line, no numbering, "
          "no quotes: one short and casual, one with a small typo, one longer and polite, one from someone whose "
          "English is a second language. Keep the exact meaning. Keep any time (like 'since 2' or 'last hour') "
          "and any side (left or right) exactly as asked, and do not add a time or a side that is not there.\n"
          "Question: {q}")


@app.function(gpu="L4", timeout=1500)
def paraphrase(seeds: list) -> dict:
    import vllm
    from vllm import LLM, SamplingParams
    llm = LLM(MODEL, max_model_len=2048, gpu_memory_utilization=0.9)
    convs = [[{"role": "user", "content": PROMPT.format(q=s)}] for s in seeds]
    outs = llm.chat(convs, SamplingParams(temperature=0.9, top_p=0.95, max_tokens=200, seed=3))
    return {"version": vllm.__version__, "texts": [o.outputs[0].text for o in outs]}


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
    print(f"{len(picked)} seeds; about $0.25 on one L4")
    res = paraphrase.remote([r["q"] for r in picked])
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
    print(f"vllm {res['version']}, {MODEL}: kept {len(out)}, dropped {dropped}")
