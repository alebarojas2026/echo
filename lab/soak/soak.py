"""Soak and chaos test: the whole software stack for hours, with faults injected.

    python lab/soak/soak.py --hours 2.2 --out lab/soak/runs/r1
    python lab/soak/report.py lab/soak/runs/r1

The sim feed (lab/soak/feeder.py: sim.send's loop, cycling the paths in one process) ->
lab/soak/proxy.py (drops, duplicates, jitter, a silent link, camera off) -> bus -> brain ->
narrator (template mode: no model is listening) and the screen in headless Chromium (?src=ws,
lab/soak/probe.mjs). Every few minutes one fault from CHAOS. Everything runs at real speed: bus
and brain stamp time with the wall clock, so a faster sim would only change the link rates the
brain judges health by. Every process but the browser runs at above-normal priority, so other
load on a shared PC doesn't starve them (the board runs nothing else at their level).

Writes to --out: logs/<process>.log, monitor.jsonl (connects, gaps, transitions, events, contract
errors), proxy.jsonl (pauses in the sim feed), segments.jsonl (which path played when),
chaos.jsonl, procs.jsonl (RSS, handles, CPU every 10 s), probe.jsonl (the screen every 500 ms),
sessions/ (the bus's recordings), summary.json.
Dev only. Needs psutil and websockets; `npm install` in lab/soak for the probe.
"""
import argparse
import asyncio
import glob
import json
import os
import random
import socket
import subprocess
import sys
import threading
import time
from collections import Counter
from pathlib import Path

import psutil
from websockets.asyncio.client import connect

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))
from contracts.check import errors  # noqa: E402

PY = sys.executable
BUS, BRAIN_IN, PROXY, PROXY_CTL, WS, WEB = 5600, 5601, 5610, 5611, 8765, 8080
LINKS = ["pi5>unoq:wifi", "pi5>unoq:ble", "east>unoq:ble", "west>unoq:ble", "east>pi5:ble", "west>pi5:ble"]
CYCLE = ["zone_tour", "stand_still", "metal_object", "wave_checkin", "dropped_link", "camera_unplug", "empty_room"]
TRAINING = [("empty_room", "train"), ("zone_tour", "train"), ("stand_still", "train"),
            ("metal_object", "object"), ("wave_checkin", "train"), ("zone_tour", "train")]
CHAOS = ["packets", "silence", "cam", "brain", "router", "reset", "bus"]


def now():
    return time.time()


class Run:
    def __init__(self, out):
        self.out = Path(out)
        (self.out / "logs").mkdir(parents=True, exist_ok=True)
        self._files, self._lock = {}, threading.Lock()
        self.stop = threading.Event()

    def log(self, name, **rec):
        rec.setdefault("t", round(now(), 3))
        with self._lock:
            f = self._files.get(name) or self._files.setdefault(name, open(self.out / name, "a", encoding="utf-8"))
            f.write(json.dumps(rec) + "\n")
            f.flush()


class Procs:
    def __init__(self, run, chrome):
        out = run.out
        self.run, self.procs, self.starts, self._ps, self._logs = run, {}, Counter(), {}, {}
        self.argv = {
            "bus": [PY, "-m", "bus", "--host", "127.0.0.1", "--port", str(BUS), "--forward", f"127.0.0.1:{BRAIN_IN}",
                    "--sessions", str(out / "sessions")],
            "brain": [PY, "-m", "brain.main", "--bus-port", str(BRAIN_IN), "--ws-port", str(WS), "--ws-host", "127.0.0.1",
                      "--mode-file", str(out / "label_mode")],
            "narrator": [PY, "-m", "narrator.narrate", "--llm", "http://127.0.0.1:9", "--bus", f"127.0.0.1:{BUS}"],
            "web": [PY, "board/serve.py", "--host", "127.0.0.1", "--port", str(WEB)],
            "probe": ["node", str(HERE / "probe.mjs"), f"http://127.0.0.1:{WEB}/?src=ws"] + ([chrome] if chrome else []),
            "proxy": [PY, str(HERE / "proxy.py"), "--listen", str(PROXY), "--bus", f"127.0.0.1:{BUS}", "--control", str(PROXY_CTL)],
            "feeder": [PY, str(HERE / "feeder.py"), str(PROXY)],
        }

    def start(self, name):
        self.starts[name] += 1
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        stdin = None
        if name in ("probe", "proxy"):
            out, err = open(self.run.out / f"{name}.jsonl", "a"), open(self.run.out / "logs" / f"{name}.log", "a")
        elif name == "feeder":
            stdin, out, err = subprocess.PIPE, subprocess.PIPE, open(self.run.out / "logs" / "feeder.log", "a")
        else:
            if name in self._logs:
                self._logs[name].close()
            out = err = self._logs[name] = open(self.run.out / "logs" / f"{name}.log", "a", encoding="utf-8")
            out.write(f"=== soak: start #{self.starts[name]} at {time.strftime('%H:%M:%S')}\n")
            out.flush()
        self.procs[name] = p = subprocess.Popen(self.argv[name], cwd=REPO, stdin=stdin, stdout=out, stderr=err, env=env,
                                                text=name == "feeder", bufsize=1 if name == "feeder" else -1)
        if name != "probe":
            above_normal(p.pid)
        self.run.log("chaos.jsonl", kind="start", proc=name, pid=p.pid)
        return p

    def kill(self, name):
        p = self.procs[name]
        try:
            kids = psutil.Process(p.pid).children(recursive=True)
        except psutil.Error:
            kids = []
        p.kill()   # TerminateProcess on Windows, SIGKILL elsewhere: a crash, not a clean exit
        for k in kids:
            try:
                k.kill()
            except psutil.Error:
                pass
        p.wait(10)
        self.run.log("chaos.jsonl", kind="kill", proc=name, pid=p.pid)

    def _proc(self, pid):
        if pid not in self._ps:
            self._ps[pid] = psutil.Process(pid)
            self._ps[pid].cpu_percent(None)
        return self._ps[pid]

    def sample(self):
        for name, p in list(self.procs.items()):
            try:
                ps = self._proc(p.pid)
                group = [ps] + ([self._proc(c.pid) for c in ps.children(recursive=True)] if name == "probe" else [])
                rss = sum(x.memory_info().rss for x in group)
                handles = sum(x.num_handles() if hasattr(x, "num_handles") else x.num_fds() for x in group)
                cpu = sum(x.cpu_percent(None) for x in group)
                self.run.log("procs.jsonl", proc=name, pid=p.pid, rss=rss, handles=handles, cpu=round(cpu, 1),
                             threads=sum(x.num_threads() for x in group), alive=p.poll() is None)
            except psutil.Error:
                self.run.log("procs.jsonl", proc=name, pid=p.pid, alive=False)
        self.run.log("procs.jsonl", proc="system", cpu=psutil.cpu_percent(None))


def above_normal(pid):
    try:
        psutil.Process(pid).nice(psutil.ABOVE_NORMAL_PRIORITY_CLASS if os.name == "nt" else -5)
    except (psutil.Error, AttributeError, OSError):
        pass


class ProxyCtl:
    """Sends a fault to lab/soak/proxy.py and returns its counts."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(2)

    def __call__(self, **cmd):
        self.sock.sendto(json.dumps(cmd).encode(), ("127.0.0.1", PROXY_CTL))
        try:
            return json.loads(self.sock.recv(65535))
        except (socket.timeout, OSError):
            return {}


class Monitor:
    """A screen of our own on the brain's WebSocket: checks every message and watches the state."""

    def __init__(self, run, ctx):
        self.run, self.ctx = run, ctx
        self.loop = asyncio.new_event_loop()
        self.ws, self.state, self.state_t = None, None, None
        self.counts, self.bad, self.rate = Counter(), Counter(), Counter()
        self.last_seq, self.seq_jumps, self.examples = None, 0, 0
        self.events = []    # (arrival time, kind)
        self.prev = {}
        self.cond = threading.Condition()
        threading.Thread(target=self.loop.run_forever, daemon=True, name="monitor").start()
        asyncio.run_coroutine_threadsafe(self._run(), self.loop)

    async def _run(self):
        while not self.run.stop.is_set():
            try:
                async with connect(f"ws://127.0.0.1:{WS}/ws", open_timeout=2, max_size=None) as ws:
                    self.ws, self.last_seq = ws, None
                    self.run.log("monitor.jsonl", kind="connect")
                    async for raw in ws:
                        self.handle(json.loads(raw), now())
            except Exception as e:   # the brain is down or restarting
                if self.ws is not None:
                    self.run.log("monitor.jsonl", kind="disconnect", why=type(e).__name__)
            self.ws = None
            await asyncio.sleep(0.25)

    def handle(self, msg, t):
        kind = msg.get("type")
        self.counts[kind] += 1
        errs = errors(msg)
        new = False
        for e in errs:
            key = f"{kind} {e.split(':')[0]}"
            new = new or key not in self.bad
            self.bad[key] += 1
        if new or (errs and self.examples < 20):   # one example of every new kind of error
            self.examples += 1
            self.run.log("monitor.jsonl", kind="schema", type=kind, errors=errs[:8], msg=msg)
        seq = msg.get("seq")
        if self.last_seq is not None and seq != self.last_seq + 1:
            self.seq_jumps += 1
        self.last_seq = seq
        where = {"path": self.ctx.path, "chaos": self.ctx.chaos, "training": self.ctx.training}
        if kind == "event":
            self.events.append((t, msg.get("kind")))
            self.run.log("monitor.jsonl", kind="event", ev=msg["kind"], info=msg.get("info"), id=msg.get("id"), **where)
        elif kind == "state":
            if self.state_t is not None and t - self.state_t > 1.0:
                self.run.log("monitor.jsonl", kind="gap", gap_s=round(t - self.state_t, 3), **where)
            self.rate[int(t // 10) * 10] += 1
            if self.counts["state"] % 600 == 1:
                self.run.log("monitor.jsonl", kind="sample", lag_ms=round(t * 1000 - msg["t"]), state=msg)
            pred, alert = msg.get("pred"), msg.get("alert") or {}
            watch = {"health": (msg.get("health") or {}).get("status"), "blind": tuple((msg.get("health") or {}).get("blind") or ()),
                     "alert": alert.get("state"), "checkin": (msg.get("checkin") or {}).get("t"),
                     "pred": None if pred is None else "set", "cam": msg.get("cam"), "router": msg.get("router"),
                     "trained": (msg.get("model") or {}).get("trained"), "links": len(msg.get("links") or []),
                     "narration": (msg.get("narration") or {}).get("event_id")}
            for k, v in watch.items():
                if self.prev.get(k, "_") != v:
                    self.run.log("monitor.jsonl", kind="trans", what=k, frm=self.prev.get(k), to=v, **where)
                    self.prev[k] = v
            with self.cond:
                self.state, self.state_t = msg, t
                self.cond.notify_all()

    def wait(self, test, timeout):
        """Block until a state passes test(state); returns seconds waited or None on timeout."""
        t0 = now()

        def ok(s):
            try:
                return bool(test(s))
            except (KeyError, TypeError, IndexError):
                return False
        with self.cond:
            while not (self.state is not None and self.state_t >= t0 and ok(self.state)):
                left = timeout - (now() - t0)
                if left <= 0 or self.run.stop.is_set():
                    return None
                self.cond.wait(min(left, 0.5))
        return round(now() - t0, 2)

    def wait_event(self, kind, since, timeout):
        """Seconds from `since` until an event of this kind arrives, or None."""
        end = now() + timeout
        while now() < end and not self.run.stop.is_set():
            for t, k in list(self.events):
                if k == kind and t >= since:
                    return round(t - since, 2)
            time.sleep(0.5)
        return None

    def send(self, cmd, **args):
        for _ in range(100):   # up to 10 s for the brain to come back
            ws = self.ws
            if ws is not None:
                fut = asyncio.run_coroutine_threadsafe(ws.send(json.dumps({"v": 2, "type": "cmd", "cmd": cmd, "args": args})), self.loop)
                try:
                    fut.result(5)
                    self.run.log("chaos.jsonl", kind="cmd", cmd=cmd, args=args)
                    return True
                except Exception:
                    pass
            time.sleep(0.1)
        self.run.log("chaos.jsonl", kind="cmd_failed", cmd=cmd)
        return False


class Ctx:
    path = chaos = feeder = None
    training = False


def play(run, ctx, path, seed, training=False):
    ctx.path, feeder = path, ctx.feeder
    t0 = now()
    feeder.stdin.write(f"{path} {seed}\n")
    for line in feeder.stdout:
        if '"end"' in line:
            break
    run.log("segments.jsonl", path=path, seed=seed, start=round(t0, 3), end=round(now(), 3), training=training)


def train(run, ctx, mon, rnd):
    """What the operator does after a cold start: baseline in an empty room, record, train."""
    ctx.training = True
    t0 = now()
    mon.wait(lambda s: True, 30)
    mon.send("baseline")
    play(run, ctx, "empty_room", 100 + rnd, training=True)
    ok = mon.wait_event("baseline_done", t0, 10) is not None
    for i, (path, purpose) in enumerate(TRAINING):
        mon.send("record_start", session=f"r{rnd}-{i}-{path}", purpose=purpose, walker="sim")
        time.sleep(0.3)
        play(run, ctx, path, 200 + 10 * rnd + i, training=True)
        mon.send("record_stop")
    mon.send("train")
    trained = mon.wait_event("trained", t0, 120)
    run.log("chaos.jsonl", kind="trained", round=rnd, baseline_ok=ok, took_s=round(now() - t0, 1), trained=trained is not None)
    ctx.training = False


def driver(run, ctx, mon, need):
    rnd, i = 0, 0
    while not run.stop.is_set():
        if need.is_set():
            ctx.training = True
            need.clear()
            rnd += 1
            train(run, ctx, mon, rnd)
            continue
        play(run, ctx, CYCLE[i % len(CYCLE)], i)
        i += 1


def chaos(run, ctx, mon, procs, proxy, need, every_s, record_min):
    while ctx.training or need.is_set():
        time.sleep(1)
    rec_until = now() + record_min * 60
    mon.send("record_start", session="demo-long", purpose="demo", walker="sim")
    rnd = random.Random(1)
    for n in range(10 ** 6):
        end = now() + rnd.uniform(0.8, 1.2) * every_s
        while now() < end or ctx.training or need.is_set():
            if rec_until and now() > rec_until:
                mon.send("record_stop")
                rec_until = None
            if run.stop.wait(1):
                return
        action = CHAOS[n % len(CHAOS)]
        ctx.chaos, t0 = action, now()
        rec = {"kind": "chaos", "action": action, "start": round(t0, 3), "path": ctx.path}
        if action == "packets":
            before = proxy(packets=[0.10, 0.05, 100])
            run.stop.wait(90)
            after = proxy(packets=[0, 0, 0])
            rec["proxy"] = {k: after.get(k, 0) - v for k, v in before.items()}
        elif action == "silence":
            link = LINKS[(n // len(CHAOS)) % len(LINKS)]
            proxy(silence=[link, 10])
            rec["link"] = link
            rec["blind_s"] = mon.wait(lambda s: link in s["health"]["blind"], 15)
            rec["clear_after_silence_s"] = mon.wait(lambda s: link not in s["health"]["blind"] and now() > t0 + 10, 40)
        elif action == "cam":
            proxy(camera=False)
            rec["off_s"] = mon.wait(lambda s: s["cam"] == "off" and s["teacher"] is None, 10)
            run.stop.wait(30)
            proxy(camera=True)
            rec["on_s"] = mon.wait(lambda s: s["cam"] == "on", 10)
        elif action in ("brain", "bus"):
            procs.kill(action)
            run.stop.wait(3)
            procs.start(action)
            t1 = now()
            rec["restart_at"] = round(t1, 3)
            if action == "brain":
                rec["state_back_s"] = mon.wait(lambda s: True, 60)
                need.set()
                while need.is_set() or ctx.training:
                    time.sleep(1)
                mon.wait(lambda s: s["pred"] is not None, 60)
                rec["pred_back_s"] = round(now() - t1, 1)
            else:
                rec["links_ok_s"] = mon.wait(lambda s: s["health"]["status"] == "ok" and len(s["links"]) == 6
                                             and all(x["rate_hz"] > 0 for x in s["links"]), 60)
        elif action == "router":
            mon.send("router_moved", spot="S-W30")
            rec["pred_null_s"] = mon.wait(lambda s: s["router"] == "S-W30" and s["pred"] is None, 5)
            run.stop.wait(30)
            mon.send("router_home")
            rec["pred_back_s"] = mon.wait(lambda s: s["router"] == "S-home" and s["pred"] is not None, 60)
        elif action == "reset":
            mon.send("reset")
            rec["cleared_s"] = mon.wait(lambda s: s["alert"]["state"] == "none" and s["checkin"] is None
                                        and s["narration"] is None, 5)
        rec["end"] = round(now(), 3)
        run.log("chaos.jsonl", **rec)
        ctx.chaos = None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--hours", type=float, default=2.0)
    ap.add_argument("--out", default=str(HERE / "runs" / time.strftime("%Y%m%d-%H%M")))
    ap.add_argument("--chaos-every", type=float, default=150, help="seconds between faults")
    ap.add_argument("--record-min", type=float, default=8, help="minutes of one long demo recording")
    a = ap.parse_args()
    run, ctx = Run(a.out), Ctx()
    shells = sorted(glob.glob(os.path.expanduser("~/AppData/Local/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell.exe")))
    procs = Procs(run, shells[-1] if shells else None)
    above_normal(os.getpid())
    proxy = ProxyCtl()
    for name in ("bus", "brain", "narrator", "web", "proxy", "feeder"):
        procs.start(name)
    ctx.feeder = procs.procs["feeder"]
    mon = Monitor(run, ctx)
    procs.start("probe")
    need = threading.Event()
    need.set()
    threads = [threading.Thread(target=driver, args=(run, ctx, mon, need), daemon=True),
               threading.Thread(target=chaos, args=(run, ctx, mon, procs, proxy, need, a.chaos_every, a.record_min), daemon=True)]
    for th in threads:
        th.start()
    t_end, t_start = now() + a.hours * 3600, now()
    try:
        while now() < t_end:
            procs.sample()
            sizes = {p.name: p.stat().st_size for p in (run.out / "sessions").glob("*.jsonl")}
            run.log("procs.jsonl", proc="disk", sessions=sizes, logs={p.name: p.stat().st_size for p in (run.out / "logs").iterdir()})
            print(f"{(now() - t_start) / 60:5.1f} min  states {mon.counts['state']}  events {mon.counts['event']}  "
                  f"contract errors {sum(mon.bad.values())}  path {ctx.path}  chaos {ctx.chaos}", flush=True)
            json.dump({"counts": mon.counts, "bad": mon.bad, "seq_jumps": mon.seq_jumps, "rate": mon.rate,
                       "proxy": proxy(), "starts": procs.starts, "start": t_start, "now": now()},
                      open(run.out / "summary.json", "w"), indent=1)
            time.sleep(10)
    finally:
        run.stop.set()
        for name in list(procs.procs):
            procs.kill(name)
        print("done:", run.out)


if __name__ == "__main__":
    main()
