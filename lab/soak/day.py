"""One seeded judging day against the whole stack (simulated), for the soak farm.

    python lab/soak/day.py --seed 7 --hours 3 --pace real --out lab/soak/runs/day7
    python lab/soak/day.py --seed 7 --hours 1 --pace fast --out lab/soak/runs/day7f

The sim feed (this file with --feeder) -> lab/soak/proxy.py -> bus -> brain -> store, narrator
(lab/soak/fake_llm.py stands in for the model), board/serve.py. Back-to-back judge visits, about
3 minutes each: baseline (with or without keep_model), walk up, a live lesson on the judge with
the camera on, the camera unplugged, standing still, arm and an intruder, disarm, questions to
/ask, leave, reset. Around them, from the seed: passers-by in bursts, packet loss 0-60%, a
receiver going quiet, a beacon losing power, screens connecting and dropping (and one that
stops reading), malformed commands and datagrams, the board clock jumping, the disk filling,
and hard kills restarted after 2 s like systemd.

--pace real: visits at real length with gaps between judges, faults every few minutes.
--pace fast: the same steps with the idle parts cut and faults every 20-40 s. Bus and brain run
on the wall clock, so "fast" means more of everything per hour, never a faster clock.

Everything is simulated: rank what breaks, never quote timings (this is not the board).
Writes to --out: problems.jsonl (what broke, with context), monitor.jsonl, chaos.jsonl,
procs.jsonl (RSS, fds, threads every 30 s; store and session sizes), visits.jsonl, logs/,
summary.json. The tree's own features (store, /ask, lesson, arm, keep_model) are found by
looking at its files, so the same day runs on main and on main plus open PRs.
"""
import argparse
import asyncio
import json
import math
import os
import random
import re
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
from collections import Counter, deque
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

PY = sys.executable
BUS, BRAIN_IN, PROXY, PROXY_CTL, WS, WEB, LLM = 5600, 5601, 5610, 5611, 8765, 8080, 8091
FAKETIME_LIB = "/usr/lib/x86_64-linux-gnu/faketime/libfaketime.so.1"
CLOCKED = ("bus", "brain", "store", "web", "narrator")   # the board's own processes
KILLABLE = ("brain", "bus", "store", "narrator", "web")


def now():
    return time.time()


def has(path, text=None):
    p = REPO / path
    return p.exists() and (text is None or text in p.read_text(encoding="utf-8", errors="replace"))


# ---------------------------------------------------------------- the feed (a subprocess)

def feeder(port):
    """Reads {"path", "seed"} lines on stdin, plays each at real speed, prints {"end"} after each."""
    from sim import fake
    from sim.send import UdpOut
    from sim.wire import encoder
    import select
    out = UdpOut("127.0.0.1", port)
    encode = encoder()
    hold, n = None, 0

    import gate
    from sim.layout import LAYOUT
    nodes = json.loads((REPO / "radio" / "nodes.json").read_text(encoding="utf-8"))
    one_spot = gate.is_gate(nodes)

    def play(path, seed):
        rng = random.Random(seed)
        start_ms = int(time.time() * 1000)
        events = fake.simulate(path, rate=15.0, seed=seed)
        events = with_passers(events, path.get("passers") or [], rng, fake)
        if one_spot:   # the kit's own rates, noise and falls (issue #789), from lab/soak/gate.py
            others = [e for e in events if e["type"] != "rssi"]
            events = sorted(others + gate.readings(path, seed, nodes, LAYOUT, fake, passer_at), key=lambda e: e["t"])
        fake.pace(((e["t"], encode({**e, "t": e["t"] + start_ms / 1000})) for e in events), out=out)

    while True:
        # The radios never stop: while the day waits between paths, the last spot is held, 1 s at a time.
        if hold is not None and not select.select([sys.stdin], [], [], 0)[0]:
            n += 1
            play(hold, n)
            continue
        line = sys.stdin.readline()
        if not line:
            return
        job = json.loads(line)
        path = job["path"]
        play(path, job["seed"])
        print(json.dumps({"end": path.get("name"), "t": time.time()}), flush=True)
        last = (path.get("person") or [{"x": None}])[-1]
        hold = {"name": "hold", "duration_s": 1.0, "label_mode": path.get("label_mode", "person"),
                "person": [] if last.get("x") is None else [{"t": 0, "x": last["x"], "y": last["y"]}],
                "camera": [{"t": 0, "state": (path.get("camera") or [{"state": "on"}])[-1]["state"]}]}


def passer_at(p, t):
    if not p["t_on"] <= t < p["t_off"]:
        return None
    f = (t - p["t_on"]) / (p["t_off"] - p["t_on"])
    return (p["x0"] + f * (p["x1"] - p["x0"]), p["y"])


def with_passers(events, passers, rng, fake):
    """People walking past behind the judge: their drop on every link, and the camera sometimes sees them."""
    for e in events:
        if passers and e["type"] == "rssi":
            nodes = fake.NODES
            for p in passers:
                pos = passer_at(p, e["t"])
                if pos and e["tx"] in nodes and e["rx"] in nodes:
                    d = fake.drop(pos, nodes[e["tx"]], nodes[e["rx"]], fake.PERSON_DROP_DB, fake.PERSON_WIDTH_M)
                    e = dict(e, dbm=round(e["dbm"] - d * max(0.0, 1 + rng.gauss(0, 0.25))))
        elif passers and e["type"] == "label":
            seen = sum(1 for p in passers if p["in_frame"] and passer_at(p, e["t"]))
            if seen:
                e = dict(e, persons_in_frame=e["persons_in_frame"] + seen)
        yield e


# ---------------------------------------------------------------- the day

class Day:
    def __init__(self, a):
        from soak import Run, Monitor, ProxyCtl  # noqa: F401  (#205's harness)
        from contracts.check import errors
        from sim.layout import LAYOUT
        self.a, self.L, self.errors = a, LAYOUT, errors
        self.rng = random.Random(a.seed)
        self.out = Path(a.out)
        self.run = Run(self.out)
        self.fast = a.pace == "fast"
        r = self.rng
        self.cfg = {
            "seed": a.seed, "pace": a.pace, "hours": a.hours,
            "loss": r.choice([0.0, 0.0, 0.05, 0.1, 0.2, 0.3, 0.45, 0.6]),
            "dup": r.choice([0.0, 0.01, 0.05]), "jitter_ms": r.choice([0, 20, 100]),
            "passers_per_min": r.choice([0, 2, 4, 8, 12]),
            "keep_model_share": r.choice([0.0, 0.5, 1.0]),
            "baseline_every": r.choice([1, 1, 2, 3]),
            "kill_per_h": r.choice([0, 1, 2]) * (3 if self.fast else 1),
            "fault_every_s": (r.uniform(20, 40) if self.fast else r.uniform(90, 240)),
            "clock_jumps": a.faketime and r.random() < 0.7,
            "disk_full": r.random() < 0.6,
        }
        self.focus = a.focus
        self.one_spot = any(l.get("crosses_spot") is True for l in json.loads(
            (REPO / "radio" / "nodes.json").read_text(encoding="utf-8"))["links"])
        if a.focus != "mix":   # one question per day: everything else quiet
            self.cfg.update(loss=r.choice([0.0, 0.02, 0.05]), dup=0.0, jitter_ms=r.choice([0, 20]), kill_per_h=0,
                            clock_jumps=False, disk_full=False, baseline_every=1, keep_model_share=0.0)
        if a.focus == "memory":
            self.cfg.update(baseline_every=10 ** 6, passers_per_min=r.choice([0, 2, 4]))
        if a.focus == "spot":
            self.cfg.update(passers_per_min=r.choice([2, 4, 6, 8, 12]), baseline_every=r.choice([1, 2, 4]))
        if a.focus in ("clock", "disk", "armed"):
            self.cfg.update(passers_per_min=r.choice([0, 2]))
        self.cfg["focus"] = a.focus
        self.feat = {
            "store": has("store/__main__.py"), "ask": has("board/serve.py", "/ask"),
            "lesson": has("brain/lesson.py"), "arm": has("brain/core.py", "_cmd_arm"),
            "keep_model": has("brain/core.py", "keep_model"),
            "brain_bus_arg": has("brain/main.py", '"--bus"'), "brain_sessions_arg": has("brain/main.py", '"--sessions"'),
        }
        self.area = tuple(self.L.strip_m or self.L.size_m)
        self.zones = sorted(self.L.centres)
        self.still_zone = self.L.still_zone()
        self.pos = None                    # the judge, (x, y) or None
        self.procs, self.starts, self.killed_at, self._logs = {}, Counter(), {}, {}
        self.problems, self.seen_problem = Counter(), Counter()
        self.visit_n, self.segment, self.chaos_now = 0, None, set()
        self.capturing_until = 0.0
        self.reset_t = None
        self.disk_full = False
        self.offset_s = 0
        self.ctx = type("Ctx", (), {"path": None, "chaos": None, "training": False})()
        self.lock, self.lock_log = threading.Lock(), threading.Lock()
        self._present = "unset"

    # ---- problems

    def problem(self, kind, once_per=None, **detail):
        """Something a judge could see go wrong. once_per: at most one record per key per that many s."""
        key = (kind, detail.get("key"))
        t = now()
        if once_per is not None and t - self.seen_problem.get(key, -1e9) < once_per:
            return
        self.seen_problem[key] = t
        self.problems[kind] += 1
        self.run.log("problems.jsonl", kind=kind, visit=self.visit_n, segment=self.segment,
                     chaos=sorted(self.chaos_now), clock_offset_s=self.offset_s, disk_full=self.disk_full, **detail)

    # ---- processes

    def argv(self, name):
        o = self.out
        brain = [PY, "-m", "brain.main", "--bus-port", str(BRAIN_IN), "--ws-port", str(WS), "--ws-host", "127.0.0.1",
                 "--mode-file", str(o / "label_mode")]
        if self.feat["brain_bus_arg"]:
            brain += ["--bus", f"127.0.0.1:{BUS}"]
        if self.feat["brain_sessions_arg"]:
            brain += ["--sessions", str(o / "sessions")]
        web = [PY, "board/serve.py", "--host", "127.0.0.1", "--port", str(WEB)]
        if self.feat["ask"]:
            web += ["--store", str(o / "store.db"), "--llm", f"http://127.0.0.1:{LLM}"]
        return {
            "bus": [PY, "-m", "bus", "--host", "127.0.0.1", "--port", str(BUS), "--forward", f"127.0.0.1:{BRAIN_IN}",
                    "--sessions", str(o / "sessions")],
            "brain": brain,
            "store": [PY, "-m", "store", "--db", str(o / "store.db"), "--ws", f"ws://127.0.0.1:{WS}/ws"],
            "llm": [PY, str(HERE / "fake_llm.py"), "--port", str(LLM), "--seed", str(self.a.seed)],
            "narrator": [PY, "-m", "narrator.narrate", "--ws", f"ws://127.0.0.1:{WS}/ws",
                         "--llm", f"http://127.0.0.1:{LLM}", "--bus", f"127.0.0.1:{BUS}"],
            "web": web,
            "proxy": [PY, str(HERE / "proxy.py"), "--listen", str(PROXY), "--bus", f"127.0.0.1:{BUS}",
                      "--control", str(PROXY_CTL), "--seed", str(self.a.seed)],
            "feeder": [PY, str(HERE / "day.py"), "--feeder", str(PROXY)],
        }[name]

    def start(self, name):
        self.starts[name] += 1
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        if name in CLOCKED and self.a.faketime:
            env.update(LD_PRELOAD=FAKETIME_LIB, FAKETIME_TIMESTAMP_FILE=str(self.out / "faketime"),
                       FAKETIME_CACHE_DURATION="1", FAKETIME_DONT_FAKE_MONOTONIC="1")
        log = self._logs.get(name)
        if log is None:
            log = self._logs[name] = open(self.out / "logs" / f"{name}.log", "a", encoding="utf-8")
        log.write(f"=== day: start #{self.starts[name]} at {time.strftime('%H:%M:%S')}\n")
        log.flush()
        if name == "feeder":
            p = subprocess.Popen(self.argv(name), cwd=REPO, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=log, text=True, bufsize=1)
        else:
            # Through a pipe, like journald on the board: a full disk doesn't stop a process saying why it died.
            p = subprocess.Popen(self.argv(name), cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            threading.Thread(target=self._copy, args=(p.stdout, log), daemon=True).start()
        self.procs[name] = p
        self.run.log("chaos.jsonl", kind="start", proc=name, pid=p.pid)
        return p

    def _copy(self, pipe, log):
        for raw in iter(pipe.readline, b""):
            with self.lock_log:
                log.write(raw.decode("utf-8", "replace"))
                log.flush()

    def faketime_works(self):
        """libfaketime, a timestamp file and Python's time.time(): does an offset reach the process?"""
        if not Path(FAKETIME_LIB).exists():
            return False
        f = self.out / "faketime-test"
        f.write_text("+100000\n")
        env = dict(os.environ, LD_PRELOAD=FAKETIME_LIB, FAKETIME_TIMESTAMP_FILE=str(f), FAKETIME_DONT_FAKE_MONOTONIC="1")
        try:
            t = float(subprocess.run([PY, "-c", "import time; print(time.time())"], env=env, capture_output=True,
                                     text=True, timeout=20).stdout)
        except (ValueError, subprocess.SubprocessError):
            return False
        return abs(t - now() - 100000) < 60

    def kill(self, name, why="chaos"):
        p = self.procs.get(name)
        if p is None:
            return
        self.killed_at[name] = now()
        import psutil
        try:
            kids = psutil.Process(p.pid).children(recursive=True)   # a venv launcher on Windows has the real one
        except psutil.Error:
            kids = []
        for k in [p, *kids]:
            try:
                k.kill()
            except Exception:
                pass
        try:
            p.wait(10)
        except Exception:
            pass
        self.run.log("chaos.jsonl", kind="kill", proc=name, pid=p.pid, why=why)

    def supervise(self):
        """systemd's Restart=always, RestartSec=2: anything that exits comes back. An exit we didn't
        cause is a crash."""
        for name, p in list(self.procs.items()):
            code = p.poll()
            if code is None:
                continue
            ours = now() - self.killed_at.get(name, -1e9) < 30
            if not ours:
                self.problem("crash", proc=name, key=name, exit=code, log_tail=self.tail(name, 40))
            self.killed_at[name] = now()   # a restart window, not a second crash
            time.sleep(2)
            if name == "feeder":
                with self.lock:
                    self.start(name)
            else:
                self.start(name)

    def tail(self, name, n):
        try:
            lines = (self.out / "logs" / f"{name}.log").read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        return lines[-n:]

    def scan_logs(self, offsets):
        """Every traceback (and every ERROR-level line) in the logs, once per distinct last line."""
        for f in (self.out / "logs").glob("*.log"):
            name = f.stem
            try:
                with open(f, encoding="utf-8", errors="replace") as fh:
                    fh.seek(offsets.get(name, 0))
                    text = fh.read()
                    offsets[name] = fh.tell()
            except OSError:
                continue
            lines = text.splitlines()
            i = 0
            while i < len(lines):
                line = lines[i]
                if line.startswith("Traceback"):
                    block = [lines[i - 1]] if i else []
                    block.append(line)
                    i += 1
                    while i < len(lines) and lines[i].startswith((" ", "\t")):
                        block.append(lines[i])
                        i += 1
                    if i < len(lines):   # the exception line itself
                        block.append(lines[i])
                        i += 1
                    last = block[-1].strip()
                    sig = re.sub(r"\d+", "N", last)[:160]
                    self.problem("traceback", proc=name, key=f"{name}:{sig}", once_per=1e9, last=last,
                                 excerpt=block[-25:])
                    continue
                if re.search(r"\b(ERROR|CRITICAL)\b|Task exception was never retrieved", line):
                    sig = re.sub(r"\d+", "N", line.split(" ", 2)[-1])[:160]
                    self.problem("error_line", proc=name, key=f"{name}:{sig}", once_per=1e9, line=line[:400])
                i += 1

    def sample(self):
        import psutil
        for name, p in list(self.procs.items()):
            try:
                ps = psutil.Process(p.pid)
                self.run.log("procs.jsonl", proc=name, pid=p.pid, rss=ps.memory_info().rss, fds=ps.num_fds(),
                             threads=ps.num_threads(), cpu_s=round(sum(ps.cpu_times()[:2]), 1))
            except (psutil.Error, AttributeError):
                pass
        sizes = {}
        for suffix in ("", "-wal", "-shm"):
            f = self.out / f"store.db{suffix}"
            sizes["store.db" + suffix] = f.stat().st_size if f.exists() else 0
        sess = self.out / "sessions"
        sizes["sessions"] = sum(f.stat().st_size for f in sess.glob("*") if f.is_file()) if sess.exists() else 0
        sizes["logs"] = sum(f.stat().st_size for f in (self.out / "logs").glob("*"))
        self.run.log("procs.jsonl", proc="disk", **sizes)
        self.run.log("procs.jsonl", proc="system", cpu=psutil.cpu_percent(None),
                     mem_used=psutil.virtual_memory().used)

    # ---- paths

    def seg(self, name, dur, moves, cam="on", waves=None, passers=True):
        """A path for the feed. moves: [(t, (x, y) or None)], from the judge's current spot."""
        pts = [(0.0, self.pos)] + list(moves)
        person = [{"t": round(t, 2), "x": None if p is None else round(p[0], 3), "y": None if p is None else round(p[1], 3)}
                  for t, p in pts]
        if person and person[0]["x"] is None and all(w["x"] is None for w in person):
            person = []
        self.pos = pts[-1][1]
        path = {"name": name, "duration_s": dur, "person": person, "camera": [{"t": 0, "state": cam}],
                "label_mode": "person", "waves": waves or [], "passers": self.passers(dur) if passers else []}
        return path

    def passers(self, dur):
        rate = self.cfg["passers_per_min"] * (3 if self.rng.random() < 0.15 else 1)   # bursts
        out, t = [], 0.0
        w, h = self.area
        while rate:
            t += self.rng.expovariate(rate / 60)
            if t >= dur:
                break
            speed = self.rng.uniform(0.6, 1.4)
            x0, x1 = (-0.6, w + 0.6) if self.rng.random() < 0.5 else (w + 0.6, -0.6)
            span = abs(x1 - x0) / speed
            y = self.rng.uniform(-0.35, 0.05) if self.L.strip_m else self.rng.uniform(-0.5, -0.05)
            cut = False
            if self.one_spot:   # behind Pi B (y -0.2), 0.1-0.65 m from it; one in ten cuts through the gap
                cut = self.rng.random() < 0.1
                y = self.rng.uniform(0.1, 0.5) if cut else self.rng.uniform(-0.85, -0.3)
            out.append({"t_on": t, "t_off": t + span, "x0": x0, "x1": x1, "y": y,
                        "in_frame": self.rng.random() < 0.5, "cut": cut})
        return out

    def spot(self, zone, jitter=0.12):
        cx, cy = self.L.centres[zone]
        return (cx + self.rng.uniform(-jitter, jitter), cy + self.rng.uniform(-jitter, jitter))

    def outside(self):
        w, _ = self.area
        if self.one_spot:   # the judge steps into the gap from one side
            return (-0.5 if self.rng.random() < 0.5 else w + 0.5, self.rng.uniform(0.2, 0.4))
        return (self.rng.uniform(0.1, w - 0.1), -0.45)

    def play(self, path):
        self.segment = path["name"]
        self.ctx.path = path["name"]
        t0 = now()
        for _ in range(3):
            with self.lock:
                f = self.procs["feeder"]
                try:
                    f.stdin.write(json.dumps({"path": path, "seed": self.rng.randrange(10 ** 9)}) + "\n")
                    f.stdin.flush()
                except (OSError, ValueError):
                    time.sleep(3)
                    continue
            while True:
                line = f.stdout.readline()
                if not line or '"end"' in line:
                    break
            if line:
                break
            time.sleep(3)   # the feeder died; the supervisor brings it back
        self.run.log("segments.jsonl", path=path["name"], start=round(t0, 3), end=round(now(), 3),
                     passers=len(path.get("passers") or []), visit=self.visit_n,
                     person=path.get("person"), passer_list=path.get("passers"), dur=path["duration_s"])

    # ---- one visit

    def visit(self):
        self.visit_n += 1
        v, m, r, fast = self.visit_n, self.mon, self.rng, self.fast
        rec = {"visit": v, "start": round(now(), 1)}
        # Between judges: reset, then (some visits) a new baseline with the area empty and the camera on.
        self.cmd("reset")
        self.reset_t = now()
        rec["reset_clear_s"] = self.check_reset("reset")
        if v == 1 or v % self.cfg["baseline_every"] == 0:
            keep = self.feat["keep_model"] and r.random() < self.cfg["keep_model_share"] and v > 1
            rec["baseline"] = "keep_model" if keep else "new"
            self.cmd("baseline", **({"keep_model": True} if keep else {}))
            self.capturing_until = now() + 125
            if self.focus == "disk" and v > 1:
                threading.Thread(target=self.disk_at_baseline_end, args=(v,), daemon=True).start()
            t0 = now()
            self.play(self.seg("empty-baseline", 24, [(0.5, None)]))
            while m.wait_event("baseline_done", t0, 0.1) is None and now() - t0 < 90:
                self.play(self.seg("empty-wait", 8, [(0.5, None)]))
            rec["baseline_s"] = m.wait_event("baseline_done", t0, 0.1)
            self.capturing_until = 0
            if not keep:
                self.cmd("record_start", session=f"v{v}-empty", purpose="train", walker="sim")
                self.play(self.seg("empty-train", 12, []))
                self.cmd("record_stop")
        # Walk up.
        a = r.choice(self.zones)
        t0 = now()
        self.play(self.seg("arrive", 4, [(0.2, self.outside()), (2.5, self.spot(a)), (4, self.spot(a, 0.05))]))
        st = m.state or {}
        if (st.get("model") or {}).get("trained"):
            rec["found_s"] = m.wait(lambda s: s["pred"] and s["pred"]["present"], 12)
        # The live lesson: camera on, label mode person, a train recording, steps left and right.
        self.cmd("label_mode", mode="person")
        self.cmd("record_start", session=f"v{v}-lesson", purpose="train", walker="judge")
        moves, t = [], 0.0
        for k in range(8 if not fast else 6):
            z = self.zones[k % len(self.zones)]
            t += r.uniform(1.0, 1.6)
            moves.append((t, self.spot(z)))
            t += r.uniform(1.0, 2.0)
            moves.append((t, self.pos if not moves else moves[-1][1]))
        half = t / 2
        first, second = [mv for mv in moves if mv[0] <= half], [(mv[0] - half, mv[1]) for mv in moves if mv[0] > half]
        self.play(self.seg("lesson-a", round(half, 1), first))
        self.cmd("train")        # with the recording open: the live lesson where the tree has it
        rec["lesson_train_sent"] = True
        self.play(self.seg("lesson-b", round(t - half, 1) + 0.5, second))
        # Unplug the camera, stop the recording, train again.
        self.play(self.seg("unplug", 3, [(3, self.pos)], cam="off"))
        self.cmd("record_stop")
        self.cmd("label_mode", mode="off")
        self.cmd("train")
        rec["trained_s"] = m.wait_event("trained", t0, 60)
        # Standing still where the no-movement alert counts.
        limit = self.L.zones.get(self.still_zone) or 10
        sz = self.spot(self.still_zone, 0.05)
        self.play(self.seg("walk-still", 3, [(2.5, sz)], cam="off"))
        tq = now()
        self.play(self.seg("still", limit + (15 if fast else 20), [], cam="off"))
        rec["alert_s"] = m.wait_event("alert_on", tq, 0.1)
        if r.random() < 0.5:   # a wave clears it; otherwise the next reset does
            self.play(self.seg("wave", 5, [], cam="off", waves=[{"t_on": 0.5, "t_off": 4.0, "link": "pi5>unoq:wifi",
                                                                   "amp_db": 4.0, "hz": 2.0}]))
        # Armed: step away, arm, step back in.
        if self.feat["arm"]:
            self.play(self.seg("step-out", 5, [(2, self.outside()), (2.2, None)], cam="off"))
            self.cmd("arm", on=True)
            if self.focus == "armed":   # the brain restarts while armed (systemd brings it back)
                self.mon.wait(lambda s: s.get("armed"), 3)
                tk = now()
                self.kill("brain", why="armed-restart")
                back = self.mon.wait(lambda s: True, 30)
                armed = self.mon.wait(lambda s: s.get("armed"), 10)
                said = self.mon.wait_event("disarmed", tk, 0.1)
                rec["armed_restart"] = {"state_back": back is not None, "armed_after": armed is not None,
                                        "disarmed_event": said is not None}
                if back is not None and armed is None and said is None:
                    self.problem("armed_lost_on_restart", key="brain", once_per=1e9)
            ti = now()
            b = r.choice(self.zones)
            self.play(self.seg("intruder", 9, [(0.1, self.outside()), (2.5, self.spot(b))], cam="off"))
            rec["intrusion_s"] = m.wait_event("intrusion", ti, 0.1)
            if r.random() < 0.7:
                self.cmd("arm", on=False)
                rec["disarm_clear_s"] = m.wait(lambda s: not s.get("armed"), 3)
                if rec["disarm_clear_s"] is None:
                    self.problem("armed_after_disarm", key="disarm")
            # else: left armed on purpose; the reset at the next visit must disarm.
        # Questions while they talk.
        if self.feat["ask"]:
            threading.Thread(target=self.ask_some, args=(r.randint(1, 3),), daemon=True).start()
        if not fast:
            for _ in range(r.randint(2, 5)):
                z = r.choice(self.zones)
                self.play(self.seg("talk", r.uniform(6, 14), [(r.uniform(1, 2), self.spot(z))], cam="off"))
        # Leave; the camera is plugged back in for the next judge.
        self.play(self.seg("leave", 4, [(2.5, self.outside()), (2.7, None)], cam="on"))
        if not fast and r.random() < 0.6:
            self.play(self.seg("between", r.uniform(5, 60), []))
        rec["end"] = round(now(), 1)
        self.run.log("visits.jsonl", **rec)

    def check_reset(self, why):
        """After reset: alert none, no check-in, no narration, not armed."""
        def clean(s):
            return s["alert"]["state"] != "check_on" and s["checkin"] is None and not s.get("armed")   # counting may restart at once
        took = self.mon.wait(clean, 5)
        if took is None and self.mon.state is not None:
            s = self.mon.state
            left = {k: v for k, v in (("alert", s["alert"]), ("checkin", s["checkin"]), ("armed", s.get("armed")))
                    if (k == "alert" and v["state"] == "check_on") or (k != "alert" and v)}
            if left:
                self.problem("reset_left_state", key=",".join(sorted(left)), once_per=600, left=left, after=why)
        return took

    def cmd(self, cmd, **args):
        ok = self.mon.send(cmd, **args)
        if not ok:
            self.problem("cmd_not_sent", key=cmd, once_per=300, cmd=cmd)
        return ok

    # ---- /ask

    QUESTIONS = ["was anyone here in the last 10 minutes?", "any alerts?", "was there an intrusion while armed?",
                 "how long was someone still?", "which link is weakest?", "was the model trained in the cloud?",
                 "who was that?", "how many people walked past?", "anyone at the desk in the last hour?",
                 "what's the weather", "", "   ", "x" * 5000, "🙂 anyone?", "any alerts in the last 99999 minutes?"]

    def ask_some(self, n):
        for _ in range(n):
            self.ask(self.rng.choice(self.QUESTIONS))

    def ask(self, q, body=None):
        data = body if body is not None else json.dumps({"question": q}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{WEB}/ask", data=data, headers={"Content-Type": "application/json"})
        t0 = now()
        code, reply = None, None
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                code, reply = resp.status, json.load(resp)
        except urllib.error.HTTPError as e:
            code = e.code
        except Exception as e:
            code = type(e).__name__
        took = round(now() - t0, 1)
        self.run.log("ask.jsonl", q=q[:80], code=code, took_s=took, tool=reply and reply.get("tool"),
                     picked_by=reply and reply.get("picked_by"), answer=(reply or {}).get("answer", "")[:200])
        bad_ok = body is not None or not q.strip() or len(q) > 2000
        if code == 200 and isinstance(reply, dict):
            missing = {"answer", "rows", "tool", "args", "picked_by", "src", "ms"} - set(reply)
            if missing:
                self.problem("ask_reply_shape", key="shape", once_per=1e9, missing=sorted(missing), q=q[:80])
        elif code in (400, 413) and bad_ok:
            pass
        elif code == 503 and self.killed_recently("web", "store"):
            pass
        else:
            if not self.killed_recently("web"):
                self.problem("ask_failed", key=str(code), once_per=600, code=code, q=q[:80], took_s=took,
                             log_tail=self.tail("web", 15))
        if took > 30:
            self.problem("ask_stuck", key="slow", once_per=600, took_s=took, q=q[:80])

    def killed_recently(self, *names, within=20):
        return any(now() - self.killed_at.get(n, -1e9) < within for n in names)

    # ---- the background: faults, screens, checks

    def faults(self):
        r = self.rng
        if self.focus == "clock":
            return self.clock_script()
        if self.focus != "mix":   # only the harmless background: screens come and go, the web is asked
            while not self.run.stop.wait(r.uniform(60, 180)):
                getattr(self, "fault_" + r.choice(["http", "stalled_screen"]))()
            return
        kinds = ["rx_off", "tx_off", "garbage", "bad_cmds", "stalled_screen", "loss_spike", "http"]
        if self.cfg["clock_jumps"]:
            kinds.append("clock")
        if self.cfg["disk_full"]:
            kinds.append("disk_full")
        next_kill = now() + (r.expovariate(self.cfg["kill_per_h"] / 3600) if self.cfg["kill_per_h"] else 1e12)
        time.sleep(60)
        while not self.run.stop.is_set():
            if self.run.stop.wait(r.uniform(0.7, 1.3) * self.cfg["fault_every_s"]):
                return
            if now() > next_kill:
                name = r.choice(KILLABLE)
                self.fault_kill(name)
                next_kill = now() + r.expovariate(self.cfg["kill_per_h"] / 3600)
                continue
            kind = r.choice(kinds)
            self.chaos_now.add(kind)
            self.ctx.chaos = kind
            t0 = now()
            try:
                getattr(self, "fault_" + kind)()
            except Exception as e:
                self.run.log("chaos.jsonl", kind="fault_error", fault=kind, err=repr(e))
            self.chaos_now.discard(kind)
            self.ctx.chaos = None
            self.run.log("chaos.jsonl", kind="fault", fault=kind, start=round(t0, 2), end=round(now(), 2),
                         visit=self.visit_n, segment=self.segment)

    def fault_kill(self, name):
        was = dict(self.mon.state or {})
        self.kill(name)   # supervise() restarts it after 2 s
        if name == "brain":
            back = self.mon.wait(lambda s: True, 30)
            if back is None:
                self.problem("no_state_after_restart", key="brain", once_per=600)
            elif (was.get("model") or {}).get("trained"):
                if self.mon.wait(lambda s: s["model"]["trained"], 20) is None:
                    self.problem("model_lost_on_restart", key="brain", once_per=1800)
            if was.get("armed") and self.mon.wait(lambda s: s.get("armed"), 15) is None:
                self.problem("armed_lost_on_restart", key="brain", once_per=1e9)

    def fault_rx_off(self):
        rx = self.rng.choice(sorted({l[1] for l in self.L.links}))
        secs = self.rng.uniform(5, 40)
        self.proxy(rx_off=[rx, secs])
        self.run.stop.wait(secs + 1)
        self.expect_links_back(f"rx {rx}")

    def fault_tx_off(self):
        tx = self.rng.choice(sorted({l[0] for l in self.L.links}))
        secs = self.rng.uniform(10, 60)
        self.proxy(tx_off=[tx, secs])
        self.run.stop.wait(secs + 1)
        self.expect_links_back(f"tx {tx}")

    def expect_links_back(self, what):
        """After a radio comes back, health must leave blind (unless something else is still wrong)."""
        if self.mon.wait(lambda s: s["health"]["status"] != "blind", 30) is None and not self.chaos_now - {"rx_off", "tx_off"}:
            self.problem("blind_after_radio_back", key=what.split()[0], once_per=900, what=what,
                         health=(self.mon.state or {}).get("health"))

    def fault_loss_spike(self):
        self.proxy(packets=[self.rng.uniform(0.3, 0.7), self.cfg["dup"], self.cfg["jitter_ms"]])
        self.run.stop.wait(self.rng.uniform(20, 60))
        self.proxy(packets=[self.cfg["loss"], self.cfg["dup"], self.cfg["jitter_ms"]])

    def fault_garbage(self):
        self.proxy(garbage=self.rng.randint(5, 60))

    BAD = ['{bad json', '[]', 'null', '{"type":"cmd"}', '{"type":"cmd","cmd":5}', '{"type":"cmd","cmd":"explode"}',
           '{"type":"cmd","cmd":"train","args":[]}', '{"type":"cmd","cmd":"label_mode","args":{"mode":7}}',
           '{"type":"cmd","cmd":"router_moved","args":{"spot":null}}',
           '{"type":"cmd","cmd":"router_moved","args":{"spot":["S-W30"]}}',
           '{"type":"cmd","cmd":"arm","args":{"on":"yes"}}', '{"type":"cmd","cmd":"truth","args":{"zone":99}}',
           '{"type":"cmd","cmd":"record_stop","args":{}}', '{"type":"cmd","cmd":"reset_alert","args":{"x":1}}',
           '{"type":"cmd","cmd":"__init__","args":{}}', '{"type":"cmd","cmd":"_tick","args":{}}',
           '{"type":"cmd","cmd":"train","args":{}}', '{"type":"cmd","cmd":"relearn","args":"x"}',
           '{"v":2,"type":"cmd","cmd":"record_start","args":{"session":{"a":1},"purpose":7}}',
           '{"v":2,"type":"cmd","cmd":"reset_alert","args":{},"extra":' + '1' * 400 + '}']

    def fault_bad_cmds(self):
        async def go():
            from websockets.asyncio.client import connect
            async with connect(f"ws://127.0.0.1:{WS}/ws", open_timeout=5, max_size=None) as ws:
                for raw in self.rng.sample(self.BAD, self.rng.randint(3, len(self.BAD))):
                    await ws.send(raw)
                if self.rng.random() < 0.3:
                    await ws.send(b"\x00\x01binary")
                if self.rng.random() < 0.2:
                    await ws.send("x" * 900_000)
                await asyncio.sleep(1)
        try:
            asyncio.run(go())
        except Exception as e:
            self.run.log("chaos.jsonl", kind="bad_cmds_err", err=repr(e))
        if self.mon.wait(lambda s: True, 5) is None and not self.killed_recently("brain"):
            self.problem("state_stopped_after_bad_cmd", key="bad", once_per=1e9, tail=self.tail("brain", 20))

    def fault_stalled_screen(self):
        """A phone that walks off the hotspot: the TCP connection stays open and nothing is read."""
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        s.settimeout(5)
        try:
            s.connect(("127.0.0.1", WS))
            s.sendall(b"GET /ws HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n")
            s.recv(1024)
            secs = self.rng.uniform(20, 90)
            t0 = now()
            gaps = []
            while now() - t0 < secs and not self.run.stop.is_set():
                gaps.append(now() - (self.mon.state_t or now()))
                time.sleep(0.5)
            worst = max(gaps) if gaps else 0
            self.run.log("chaos.jsonl", kind="stalled_screen", secs=round(secs), worst_gap_s=round(worst, 1))
            if worst > 2.5 and not self.killed_recently("brain", within=40):
                self.problem("stalled_screen_freezes_state", key="stall", once_per=1800, worst_gap_s=round(worst, 1),
                             stall_s=round(secs))
        except OSError as e:
            self.run.log("chaos.jsonl", kind="stalled_screen_err", err=repr(e))
        finally:
            s.close()

    def fault_http(self):
        paths = ["/", "/?src=ws", "/nodes.json", "/proof.json", "/index.html", "/../../etc/passwd", "/%00", "/x" * 300,
                 "/history", "/history?minutes=99999", "/history?minutes=-5", "/history?minutes=abc", "/layout"]
        for p in self.rng.sample(paths, 6):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{WEB}{p}", timeout=10) as resp:
                    code = resp.status
            except urllib.error.HTTPError as e:
                code = e.code
            except Exception as e:
                code = type(e).__name__
            if p in ("/nodes.json", "/proof.json") and code != 200 and not self.killed_recently("web"):
                self.problem("http_failed", key=p, once_per=900, path=p, code=code)
            elif isinstance(code, int) and code >= 500 and code != 503 and not self.killed_recently("web", "store"):
                self.problem("http_5xx", key=p.split("?")[0][:40], once_per=900, path=p[:80], code=code,
                             log_tail=self.tail("web", 15))
        if self.feat["ask"]:
            for body in (b"", b"{", b'{"question": 5}', b'{"q": "x"}', b"[" * 3000):
                self.ask("(malformed)", body=body)

    def fault_clock(self):
        r = self.rng
        jump = r.choice([-3600, -600, -60, -5, 5, 60, 600, 3600, 86400 * 2])
        self.set_offset(self.offset_s + jump)
        self.run.log("chaos.jsonl", kind="clock_jump", jump_s=jump, offset_s=self.offset_s)
        self.run.stop.wait(r.uniform(30, 120))
        if r.random() < 0.5:
            self.set_offset(0)
            self.run.log("chaos.jsonl", kind="clock_jump", jump_s=-jump, offset_s=0)

    def clock_script(self):
        """Round 3's blow-up, on purpose and on a schedule: 2 days forward, back 10 minutes later; an hour
        back, forward again; repeated from minute 15. RSS and CPU are sampled every 30 s as always."""
        steps = [(20, 172800), (30, 0), (45, -3600), (55, 0), (70, 172800), (75, 0)]
        t0 = now()
        while not self.run.stop.is_set():
            for at_min, off in steps:
                while now() - t0 < at_min * 60:
                    if self.run.stop.wait(5):
                        return
                self.chaos_now.add("clock")
                self.set_offset(off)
                self.run.log("chaos.jsonl", kind="clock_jump", jump_s=None, offset_s=off)
                if off == 0:
                    self.run.stop.wait(60)
                    self.chaos_now.discard("clock")
            t0 = now() - 15 * 60

    def set_offset(self, s):
        self.offset_s = int(s)
        (self.out / "faketime").write_text(f"{self.offset_s:+d}\n")

    def fault_disk_full(self):
        """The disk is full for a while: every board process that writes gets EFBIG on growth."""
        import psutil
        secs = self.rng.uniform(30, 120)
        names = [n for n in ("store", "bus", "brain") if n in self.procs]
        self.disk_full = True
        try:
            for n in names:
                try:
                    psutil.Process(self.procs[n].pid).rlimit(psutil.RLIMIT_FSIZE, (1, psutil.RLIM_INFINITY))
                except (psutil.Error, OSError, AttributeError):
                    pass
            self.run.stop.wait(secs)
        finally:
            for n in names:
                try:
                    psutil.Process(self.procs[n].pid).rlimit(psutil.RLIMIT_FSIZE, (psutil.RLIM_INFINITY, psutil.RLIM_INFINITY))
                except (psutil.Error, OSError, AttributeError):
                    pass
            self.disk_full = False
        self.run.log("chaos.jsonl", kind="disk_full", secs=round(secs), procs=names)
        if self.feat["store"]:
            time.sleep(15)
            lag = self.store_lag()
            if lag is not None and lag > 15 and not self.killed_recently("store", "brain", within=30):
                self.problem("store_stopped_after_disk_full", key="store", once_per=1e9, lag_s=lag,
                             tail=self.tail("store", 20))

    def disk_at_baseline_end(self, v):
        """Full from 15 s after the baseline is asked for until 40 s, so it finishes on a full disk; then is
        baseline_done there, is baseline.json whole, and does a restarted brain come back with it?"""
        import psutil
        t0 = now()
        time.sleep(15)
        names = [n for n in ("store", "bus", "brain") if n in self.procs]
        self.disk_full = True
        for n in names:
            try:
                psutil.Process(self.procs[n].pid).rlimit(psutil.RLIMIT_FSIZE, (1, psutil.RLIM_INFINITY))
            except (psutil.Error, OSError, AttributeError):
                pass
        time.sleep(25)
        for n in names:
            try:
                psutil.Process(self.procs[n].pid).rlimit(psutil.RLIMIT_FSIZE, (psutil.RLIM_INFINITY, psutil.RLIM_INFINITY))
            except (psutil.Error, OSError, AttributeError):
                pass
        self.disk_full = False
        done = self.mon.wait_event("baseline_done", t0, 30)
        try:
            doc = json.loads((self.out / "sessions" / "baseline.json").read_text(encoding="utf-8"))
            whole = bool(doc.get("links"))
        except (OSError, ValueError):
            whole = False
        rec = {"visit": v, "baseline_done": done is not None, "baseline_json_whole": whole}
        if v % 2 == 0:   # and a restart after it
            self.kill("brain", why="after-disk-full")
            back = self.mon.wait(lambda s: True, 30)
            rec["base_after_restart"] = (self.mon.wait(lambda s: any(l.get("base_dbm") is not None for l in s["links"]), 20)
                                         is not None) if back is not None else None
        self.run.log("disk.jsonl", **rec)
        if done is None:
            self.problem("baseline_done_lost_on_full_disk", key="done", once_per=1e9, visit=v)
        if not whole:
            self.problem("baseline_json_broken_on_full_disk", key="json", once_per=1e9, visit=v)
        if rec.get("base_after_restart") is False:
            self.problem("baseline_lost_on_restart", key="restart", once_per=1e9, visit=v)

    def proxy(self, **cmd):
        return self.proxyctl(**cmd)

    def screens(self):
        """Laptop and phone screens: connect, read for a while, close or vanish."""
        from websockets.asyncio.client import connect

        async def one():
            try:
                async with connect(f"ws://127.0.0.1:{WS}/ws", open_timeout=5, max_size=None) as ws:
                    end = now() + self.rng.uniform(0.2, 40)
                    async for raw in ws:
                        msg = json.loads(raw)
                        if msg.get("type") == "state" and now() > end:
                            break
                    if self.rng.random() < 0.4:
                        ws.transport.abort()   # the tab is closed hard, or the Wi-Fi drops
            except Exception:
                pass

        async def main():
            while not self.run.stop.is_set():
                n = self.rng.randint(0, 4)
                await asyncio.gather(*(one() for _ in range(n)), asyncio.sleep(self.rng.uniform(2, 15)))
        asyncio.run(main())

    def store_lag(self):
        """Seconds between the brain's newest state and the store's newest saved second (same clock)."""
        f = self.out / "store.db"
        if not f.exists() or self.mon.state is None:
            return None
        try:
            db = sqlite3.connect(f"file:{f}?mode=ro", uri=True, timeout=2)
            try:
                t = db.execute("select max(t) from seconds").fetchone()[0]
            finally:
                db.close()
        except sqlite3.Error as e:
            return f"error {e}"
        return None if t is None else round((self.mon.state["t"] - t) / 1000, 1)

    def checks(self):
        """Every second: states flowing, pred not stuck null, alerts that clear, the store keeping up."""
        null_since = alert_since = None
        last_store = 0
        while not self.run.stop.wait(1):
            m, t = self.mon, now()
            s = m.state
            brain_up = not self.killed_recently("brain", within=15)
            if m.state_t and t - m.state_t > 3 and brain_up and "stalled_screen" not in self.chaos_now:
                self.problem("state_gap", key="gap", once_per=120, gap_s=round(t - m.state_t, 1))
            if s is None or not brain_up:
                continue
            ok_for_pred = ((s.get("model") or {}).get("trained") and s["health"]["status"] == "ok"
                           and s["router"] == "S-home" and t > self.capturing_until and not self.chaos_now & {"clock"})
            if s["pred"] is None and ok_for_pred:
                null_since = null_since or t
                if t - null_since > 30:
                    self.problem("pred_stuck_null", key="pred", once_per=600, for_s=round(t - null_since),
                                 health=s["health"], model={k: s["model"].get(k) for k in ("trained", "ver", "training")})
            else:
                null_since = None
            if s["alert"]["state"] == "check_on":
                alert_since = alert_since or t
                if self.reset_t and self.reset_t > alert_since and t - self.reset_t > 3:   # a reset came and went
                    self.problem("alert_survives_reset", key="alert", once_per=600, alert=s["alert"])
            else:
                alert_since = None
            if self.feat["store"] and t - last_store > 30:
                last_store = t
                lag = self.store_lag()
                if isinstance(lag, str):
                    self.problem("store_unreadable", key=lag[:40], once_per=1800, err=lag)
                elif lag is not None and lag > 20 and not self.killed_recently("store", within=30) and not self.disk_full \
                        and not self.chaos_now & {"clock"}:
                    self.problem("store_behind", key="lag", once_per=900, lag_s=lag)

    # ---- the run

    def main(self):
        from soak import Monitor, ProxyCtl
        a = self.a
        (self.out / "logs").mkdir(parents=True, exist_ok=True)
        self.set_offset(0)
        if self.a.faketime and not self.faketime_works():
            self.a.faketime = self.cfg["clock_jumps"] = False
        self.cfg["faketime"] = bool(self.a.faketime)
        self.run.log("config.jsonl", cfg=self.cfg, feat=self.feat, area=self.area, zones=self.zones,
                     links=len(self.L.links), repo_head=os.environ.get("SOAK_TREE", "?"))
        self.proxyctl = ProxyCtl()
        t_start, t_end = now(), now() + a.hours * 3600
        offsets = {}
        try:
            names = ["llm", "bus", "brain", "web", "narrator", "proxy", "feeder"] + (["store"] if self.feat["store"] else [])
            for name in names:
                self.start(name)
            time.sleep(2)
            self.proxy(packets=[self.cfg["loss"], self.cfg["dup"], self.cfg["jitter_ms"]])
            self.mon = Monitor(self.run, self.ctx)
            day = self

            orig = self.mon.handle

            def handle(msg, t):
                orig(msg, t)
                if msg.get("type") == "state":
                    pred = msg.get("pred")
                    pres = None if pred is None else bool(pred.get("present"))
                    if pres != day._present:
                        day._present = pres
                        day.run.log("presence.jsonl", present=pres, armed=bool(msg.get("armed")), seg=day.segment)
                if msg.get("type") == "event" and msg.get("kind") in ("intrusion", "alert_on", "armed", "disarmed", "tamper"):
                    day.run.log("events.jsonl", kind=msg["kind"], info=msg.get("info"), visit=day.visit_n, seg=day.segment)
            self.mon.handle = handle
            for target in (self.faults, self.screens, self.checks):
                threading.Thread(target=target, daemon=True, name=target.__name__).start()

            def visits():
                while not self.run.stop.is_set() and now() < t_end - 60:
                    try:
                        self.visit()
                    except Exception as e:
                        self.problem("harness_error", key=type(e).__name__, once_per=600, err=repr(e))
                        time.sleep(5)
            threading.Thread(target=visits, daemon=True, name="visits").start()
            last_sample = 0
            while now() < t_end:
                self.supervise()
                if now() - last_sample >= 30:
                    last_sample = now()
                    self.sample()
                    self.scan_logs(offsets)
                    self.write_summary(t_start)
                    if a.sync:
                        a.sync()
                time.sleep(1)
        finally:
            self.run.stop.set()
            self.scan_logs(offsets)
            for name in list(self.procs):
                self.kill(name, why="end")
            self.write_summary(t_start, final=True)
            if a.sync:
                a.sync()

    def write_summary(self, t_start, final=False):
        m = getattr(self, "mon", None)
        doc = {"cfg": self.cfg, "feat": self.feat, "hours_run": round((now() - t_start) / 3600, 3),
               "visits": self.visit_n, "problems": dict(self.problems), "starts": dict(self.starts),
               "final": final}
        if m:
            doc.update(counts=dict(m.counts), contract=dict(m.bad), seq_jumps=m.seq_jumps)
        json.dump(doc, open(self.out / "summary.json", "w"), indent=1)


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--feeder":
        return feeder(int(sys.argv[2]))
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--hours", type=float, default=1.0)
    ap.add_argument("--pace", choices=("real", "fast"), default="real")
    ap.add_argument("--out", default=str(HERE / "runs" / time.strftime("day-%Y%m%d-%H%M")))
    ap.add_argument("--faketime", action="store_true", help="jump the board's clock (Linux with libfaketime)")
    ap.add_argument("--focus", default="mix", choices=("mix", "clock", "memory", "disk", "spot", "armed"),
                    help="one question per day; mix = every fault at random")
    a = ap.parse_args()
    a.sync = None
    Day(a).main()


if __name__ == "__main__":
    main()
