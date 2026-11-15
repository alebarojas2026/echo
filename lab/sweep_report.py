"""The sweep from start to finish, given something that runs the jobs: checks, the grid, the
winner, the one held-out score, and sweep-out/<timestamp>/. lab/sweep.py hands it Modal;
the tests hand it a plain loop.

Writes only under the out folder (sweep-out/ by default, git-ignored). Never PROOF.md or
proof.json: the board trains its own model and re-scores the chosen setting for those.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from lab import sweep_core as C

OUT = C.REPO / "sweep-out"
# Modal's CPU list prices, for the estimate only: per physical core second and per GiB second.
CORE_S_USD = 0.0000131
GIB_S_USD = 0.00000222
MEMORY_GIB = 2.0

SETTING_WORDS = {
    "window_ms": "window length (ms), brain/features.py WINDOW_MS",
    "features": "features: absolute (main) or relative to the baseline (PR #469)",
    "trees": "trees per forest, brain/train.py FOREST n_estimators",
    "depth": "tree depth, brain/train.py FOREST max_depth",
    "links": "links the classifier reads",
    "lesson_s": "seconds of each walker's recording taught on (null = all)",
    "smooth": "brain/alert.py SMOOTH_DECISIONS, SMOOTH_MAJORITY",
    "moving_run": "brain/alert.py MOVING_RUN (moving decisions in a row that reset the still timer)",
    "unsure_p": "say \"not sure\" when the top zone's probability is under this (0 = never)",
}


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def run(sessions, map_jobs: Callable, score_heldout: Callable, scrubbed: bool = False, nodes=None,
        out=OUT, ledger_path=None, grid=None, cpu: float = C.CPU_PER_JOB, now: Optional[str] = None) -> dict:
    """Returns {"folder": the output folder, "refused": reason or None, ...}."""
    t_start = time.monotonic()
    grid = grid or C.GRID
    now = now or datetime.now().isoformat(timespec="seconds")
    folder = Path(out) / stamp()
    try:
        data = C.load_folder(sessions, scrubbed=scrubbed, nodes=nodes)
        ledger = C.Ledger(ledger_path or Path(out) / "sealed.json")
        tune, sealed, spent = C.split(data, ledger, now)
    except C.Refused as e:
        return _refuse(folder, str(e), [], "unknown")
    ledger.save()                     # every held-out hash is sealed before anything else happens
    ready = C.readiness(tune, sealed, spent)
    label = data["label"]
    if not ready["ok"]:
        return _refuse(folder, "No winner picked: " + ready["why"] + ".", ready["record_next"], label)

    blob = C.payload(tune, data["layout"], sealed=sealed.hashes)
    jobs, posts = C.model_jobs(grid), C.post_settings(grid)
    results = map_jobs(blob, jobs, posts)
    rows = [r for res in results for r in res["variants"]]
    job_s = sum(res["seconds"] for res in results)
    winner = C.pick(rows)
    default = next((r for r in rows if r["key"] == C.variant_key(C.DEFAULTS)), None)
    gains = {k: C.paired_gain(winner[k]["per_session"], default[k]["per_session"])
             for k in ("walker", "desk") if default and k in winner and k in default}
    curve = next((res["lesson_curve"] for res in results if res["job"]["lesson_s"] is None and
                  all(res["job"][k] == winner["variant"][k] for k in ("window_ms", "features", "trees", "depth", "links"))), [])
    links = link_table(rows, data["layout"], winner)

    held = None
    if len(sealed):
        sealed_blob = C.sealed_payload(sealed, winner["variant"], data["layout"])
        scored = score_heldout(blob, sealed_blob, [winner["variant"], C.DEFAULTS])
        for h in sealed.hashes:
            ledger.mark_scored(h, now)
        ledger.save()
        held = {"sessions": sealed.ids, "chosen": _strip(scored[0]), "defaults": _strip(scored[1]),
                "gain": C.paired_gain(scored[0]["per_session"], scored[1]["per_session"])}
    report = {"label": label, "folder": str(folder), "refused": None, "readiness": ready,
              "variants": len(rows), "jobs": len(jobs), "winner": winner, "default": default, "gains": gains,
              "lesson_curve": curve, "links": links, "heldout": held, "spent_heldout": [s["id"] for s in spent],
              "job_seconds": job_s, "cpu": cpu,
              "cost_usd": round(job_s * (cpu * CORE_S_USD + MEMORY_GIB * GIB_S_USD), 3),
              "wall_s": round(time.monotonic() - t_start, 1), "top": sorted(
                  (r for r in rows if r["objective"] is not None), key=lambda r: -r["objective"])[:15]}
    write(folder, report, rows)
    return report


def _strip(r):
    return {k: v for k, v in r.items() if k != "per_session"}


def link_table(rows: List[dict], layout: dict, winner: Optional[dict] = None) -> List[dict]:
    """One row per link subset, in the shape of PR #487's device table (name, nodes, links,
    zone correct/total), at today's other settings so only the links change, plus the best tuned
    score for that subset."""
    out = []
    for sub in C.link_subsets(layout):
        mine = [r for r in rows if r["variant"]["links"] == sub["name"] and r.get("walker")]
        basis = "today's settings"
        same = next((r for r in mine if r["key"] == C.variant_key(dict(C.DEFAULTS, links=sub["name"]))), None)
        if same is None and winner:    # a small grid without today's forest: the chosen settings instead
            basis = "the chosen settings"
            same = next((r for r in mine if r["key"] == C.variant_key(dict(winner["variant"], links=sub["name"]))), None)
        best = C.pick(mine)
        w = same["walker"] if same else None
        out.append({"name": sub["name"], "nodes": sub["nodes"], "links": sub["links"],
                    "zone": {"correct": w["raw_correct"] if w else None, "total": w["windows"] if w else None,
                             "ci95": w["zone_ci95"] if w else None},
                    "best_tuned": None if not best else {"score": best["walker"]["score"], "ci95": best["walker"]["ci95"],
                                                         "variant": best["variant"]},
                    "method": f"leave-one-walker-out on train recordings, {basis} except the links"})
    return out


def _refuse(folder: Path, why: str, todo: List[str], label: str) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    lines = [f"# Sweep refused ({label})", "", why, ""]
    if todo:
        lines += ["Record next:", ""] + [f"{i}. {t}" for i, t in enumerate(todo, 1)]
    (folder / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"folder": str(folder), "refused": why, "record_next": todo, "label": label}


def pct(x) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def _vtext(v: dict) -> str:
    lesson = "all" if v["lesson_s"] is None else f"{v['lesson_s']} s"
    return (f"{v['window_ms']} ms | {v['features']} | {v['trees']}x{v['depth']} | {v['links']} | {lesson} | "
            f"{v['smooth'][0]}/{v['smooth'][1]} | {v['moving_run']} | {v['unsure_p']:g}")


def summary_text(rep: dict) -> str:
    """The one paragraph for a tired person."""
    w, d = rep["winner"], rep["default"]
    v = w["variant"]
    changes = [f"{k} {v[k]}" for k in C.DEFAULTS if v[k] != C.DEFAULTS[k]]
    parts = [f"({rep['label']}) Use these settings: " + (", ".join(changes) if changes else "today's defaults, unchanged") + "."]
    for kind, words in (("walker", "tested on people the model never saw"),
                        ("desk", "tested at a desk the model was never taught at")):
        g = (rep.get("gains") or {}).get(kind)
        if g and g["gain"] is not None:
            parts.append(f"On the training recordings, {words}, the zone score goes from {pct(d[kind]['score'])} now to "
                         f"{pct(w[kind]['score'])} ({g['gain']:+.1%}, 95% interval {C.fmt_ci(g['ci95'])}).")
    if d:
        parts.append(f"Those are the best of {rep['variants']} tries, so they flatter the winner.")
    h = rep["heldout"]
    if h:
        hg = h["gain"]
        parts.append(f"The honest check, the sealed held-out recordings scored once: {pct(h['chosen']['score'])} for "
                     f"these settings against {pct(h['defaults']['score'])} for today's (difference "
                     f"{hg['gain']:+.1%}, 95% interval {C.fmt_ci(hg['ci95']) if hg['ci95'] else 'n/a: under two sessions'}).")
    else:
        parts.append("There was no unscored held-out recording, so nothing here is an honest score yet.")
    gw = (rep.get("gains") or {}).get("walker")
    if gw and gw["ci95"] and gw["ci95"][0] <= 0:
        parts.append("The walker-out interval includes no gain: for new people, treat this as no better than now "
                     "until more recordings say otherwise.")
    todo = rep["readiness"]["record_next"]
    parts.append("Record next: " + ("; ".join(todo) if todo else "another heldout walk by someone new, to check this once more") + ".")
    parts.append("The board still trains its own model and re-scores these settings for PROOF.md.")
    return " ".join(parts)


def write(folder: Path, rep: dict, rows: List[dict]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    label = rep["label"]
    w = rep["winner"]
    settings = {"data": label, "what": "a proposal for a PR to the brain's constants; not proof",
                "settings": w["variant"], "defaults": C.DEFAULTS, "meaning": SETTING_WORDS,
                "tuning": {k: _strip(w[k]) for k in ("walker", "desk") if k in w},
                "gain_vs_defaults": rep["gains"], "heldout": rep["heldout"],
                "objective": f"zone score (a \"not sure\" answer counts {C.UNSURE_CREDIT}) minus "
                             f"{C.STILL_WEIGHT} x still-timer error in seconds; the mean of walker-out and desk-out "
                             "when two desks exist",
                "note": "The board trains its own model and re-scores this setting for PROOF.md. "
                        "This file never goes into PROOF.md or proof.json."}
    (folder / "settings.json").write_text(json.dumps(settings, indent=1, default=str) + "\n", encoding="utf-8")

    t = [f"# Top variants ({label})", "",
         f"{rep['variants']} variants, scored leave-one-walker-out" +
         (" and leave-one-desk-out" if "desk" in (w or {}) else "") + " on train recordings only. "
         "95% intervals are a bootstrap over sessions.", "",
         "| # | window | features | forest | links | lesson | smoothing | moving run | not sure | score (walker out) | 95% | desk out | still error s | objective |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rep["top"], 1):
        t.append(f"| {i} | {_vtext(r['variant'])} | {pct(r['walker']['score'])} | {C.fmt_ci(r['walker']['ci95'])} | "
                 f"{pct(r['desk']['score']) if 'desk' in r else 'n/a'} | {r['walker']['still_err_s']:.2f} | {r['objective']:.3f} |")
    d = rep["default"]
    if d:
        t.append(f"| today | {_vtext(d['variant'])} | {pct(d['walker']['score'])} | {C.fmt_ci(d['walker']['ci95'])} | "
                 f"{pct(d['desk']['score']) if 'desk' in d else 'n/a'} | {d['walker']['still_err_s']:.2f} | {d['objective']:.3f} |")
    if rep["lesson_curve"]:
        t += ["", f"## Lesson length ({label})", "",
              "The camera teaches on one person for this long (plus the empty-strip recording at that desk); the "
              "model is then scored on the rest of that person's recording, at today's smoothing.", "",
              "| lesson | zone right | 95% | sessions |", "|---|---|---|---|"]
        for c in rep["lesson_curve"]:
            t.append(f"| {c['lesson_s']} s | {pct(c['zone_raw'])} | {C.fmt_ci(c['zone_ci95'])} | {c['sessions']} |")
    if rep["heldout"]:
        h = rep["heldout"]
        t += ["", f"## Held-out, scored once ({label})", "", "| setting | score | 95% | windows |", "|---|---|---|---|",
              f"| chosen | {pct(h['chosen']['score'])} | {C.fmt_ci(h['chosen']['ci95'])} | {h['chosen']['windows']} |",
              f"| today | {pct(h['defaults']['score'])} | {C.fmt_ci(h['defaults']['ci95'])} | {h['defaults']['windows']} |"]
    (folder / "top.md").write_text("\n".join(t) + "\n", encoding="utf-8")

    L = [f"# What each set of links buys ({label})", "",
         "Same shape as the device table in PR #487 (proof/ablation.py): the model is retrained on each link "
         f"subset ({rep['links'][0]['method'] if rep['links'] else ''}). "
         "This is a replay of recordings, not a retest with fewer devices.", "",
         "| subset | nodes | links | zone right | 95% | best tuned score |", "|---|---|---|---|---|---|"]
    for r in rep["links"]:
        z = r["zone"]
        right = f"{z['correct']} of {z['total']} ({z['correct'] / z['total']:.1%})" if z["total"] else "n/a"
        best = pct(r["best_tuned"]["score"]) if r["best_tuned"] else "n/a"
        L.append(f"| {r['name']} | {len(r['nodes'])} | {len(r['links'])} | {right} | {C.fmt_ci(z['ci95'])} | {best} |")
    (folder / "links.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (folder / "links.json").write_text(json.dumps({"data": label, "rows": rep["links"]}, indent=1) + "\n", encoding="utf-8")
    (folder / "summary.md").write_text(f"# Sweep summary ({label})\n\n{summary_text(rep)}\n\n"
                                       f"{rep['variants']} variants in {rep['jobs']} jobs; {rep['wall_s']} s end to end; "
                                       f"{rep['job_seconds']:.0f} container-seconds, about ${rep['cost_usd']}.\n",
                                       encoding="utf-8")
    with open(folder / "variants.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({k: (dict((kk, vv) for kk, vv in v.items() if kk != "per_session")
                                    if isinstance(v, dict) and k in ("walker", "desk") else v)
                                for k, v in r.items()}, default=str) + "\n")


def local_map(blob, jobs, posts, n_jobs=2):
    """Run the jobs one after another in this process (tests, or no Modal)."""
    return [C.run_job(blob, j, posts, n_jobs=n_jobs, lesson_curve=j["lesson_s"] is None) for j in jobs]
