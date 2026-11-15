"""The sealed record over a compressed judging day (simulated): the store, the board's chain keeper and the
detective, driven at real record rates on a simulated clock, as fast as the container runs.

    python lab/soak/chain_day.py day    --hours 8  --out runs/c1                 # sizes, verify and request times
    python lab/soak/chain_day.py day    --hours 26 --out runs/c2                 # crosses the 24 h prune
    python lab/soak/chain_day.py day    --hours 8  --faults --out runs/c3        # witnesses, clock steps
    python lab/soak/chain_day.py prune  --out runs/c4                            # prune, restart, anchor
    python lab/soak/chain_day.py kill   --rounds 80 --out runs/c5                # hard kills mid-write
    python lab/soak/chain_day.py open2  --rounds 60 --out runs/c6                # two processes open at once
    python lab/soak/chain_day.py disk   --out runs/c7                            # a full disk while writing

Rates: one summary a second, a judge stepping in every 2-6 minutes for 10-60 s (enter/exit events, a
passer-by now and then, arming twice an hour with an intrusion), the head every 5 s and a signature from each
of two witnesses on each head (real Ed25519 keys made here with openssl; the board's own openssl check).
Request times are in-process calls of the same functions the web server runs (no HTTP), on x86: they say
how a cost grows with the store, never what it is on the board. Simulated; rank, never quote.
"""
import argparse
import base64
import json
import os
import random
import signal
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))

STATE = {"v": 2, "type": "state", "src": "live", "cam": "off", "router": "S-home",
         "links": [{"id": "pi5>pi5b:wifi", "dbm": -47.0, "base_dbm": -47.0, "drop_db": 0.2, "rate_hz": 25.0,
                    "expected_hz": 25.0, "status": "ok", "why": 0.0},
                   {"id": "pi5b>unoq:ble", "dbm": -58.0, "base_dbm": -58.0, "drop_db": 0.4, "rate_hz": 5.8,
                    "expected_hz": 5.8, "status": "ok", "why": 0.0}],
         "health": {"status": "ok", "blind": [], "reason": None}, "objects": [],
         "alert": {"state": "none", "zone": None}, "armed": False,
         "model": {"trained": True, "ver": 1, "training": False}}


def log(out, name, **rec):
    with open(Path(out) / name, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def openssl(*args, data=None):
    return subprocess.run(["openssl", *args], input=data, capture_output=True, check=True).stdout


def keygen(folder: Path, name: str):
    folder.mkdir(parents=True, exist_ok=True)
    key = folder / f"{name}.key"
    openssl("genpkey", "-algorithm", "ed25519", "-out", str(key))
    pub = openssl("pkey", "-in", str(key), "-pubout").decode()
    return key, pub


def sign(key: Path, msg: bytes, tmp: Path) -> str:
    m, s = tmp / "msg.bin", tmp / "sig.bin"
    m.write_bytes(msg)
    openssl("pkeyutl", "-sign", "-inkey", str(key), "-rawin", "-in", str(m), "-out", str(s))
    return base64.b64encode(s.read_bytes()).decode()


def timed(fn, n=3):
    out, ms = None, []
    for _ in range(n):
        t0 = time.perf_counter()
        out = fn()
        ms.append((time.perf_counter() - t0) * 1000)
    return out, round(statistics.median(ms), 2)


def rss_mb():
    try:
        import psutil
        return round(psutil.Process().memory_info().rss / 2 ** 20, 1)
    except Exception:
        return None


def contiguous(db_path) -> dict:
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    try:
        n, lo, hi = db.execute("select count(*), min(seq), max(seq) from chain").fetchone()
        dup_e = db.execute("select count(*) from (select seq from events where seq is not null group by seq having count(*) > 1)").fetchone()[0]
        dup_s = db.execute("select count(*) from (select seq from seconds where seq is not null group by seq having count(*) > 1)").fetchone()[0]
        integ = db.execute("pragma quick_check").fetchone()[0]
    finally:
        db.close()
    return {"records": n, "first": lo, "last": hi, "gapless": n == 0 or (hi - lo + 1 == n),
            "dup_seq_events": dup_e, "dup_seq_seconds": dup_s, "quick_check": integ}


def full_verify(store) -> dict:
    """Every kept record, from the anchor to the head, in calls of at most 100,000 (as GET /chain/verify)."""
    info = store.chain_info()
    first, last = info["first_seq"], info["head"]["seq"]
    if first is None:
        return {"ok": True, "checked": 0, "ms": 0}
    ok, checked, bad, ms, at = True, 0, None, 0.0, first
    while at <= last:
        r = store.verify(at, min(last, at + 99_999))
        checked += r["checked"]
        ms += r["ms"]
        if not r["ok"]:
            ok, bad = False, r["first_bad_seq"]
            break
        at += 100_000
    return {"ok": ok, "checked": checked, "first_bad_seq": bad, "ms": round(ms, 1), "first": first, "last": last,
            "anchor": info["anchor"]}


# ---------------------------------------------------------------- one compressed day

class SimDay:
    def __init__(self, a):
        from store import Store
        from board import chain
        self.a, self.out = a, Path(a.out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.rng = random.Random(a.seed)
        self.tmp = Path(tempfile.mkdtemp(prefix="chain-"))
        self.db_path = self.out / "store.db"
        for suffix in ("", "-wal", "-shm"):
            Path(str(self.db_path) + suffix).unlink(missing_ok=True)
        # The day ends "now" on the wall clock, so the real web server can be asked about it afterwards.
        self.true_ms = int(time.time() * 1000) - int(a.hours * 3_600_000) - 60_000
        self.offset_ms = 0
        keys = {}
        self.key = {}
        for node in ("pi5", "pi5b"):
            self.key[node], keys[node] = keygen(self.tmp / "keys", node)
        self.wrong_key, _ = keygen(self.tmp / "keys", "wrong")
        self.keys_file = self.out / "witness_keys.local.json"
        self.keys_file.write_text(json.dumps(keys))
        self.store = Store(self.db_path, keep_h=a.keep_h)
        self.keeper = chain.Keeper(self.store, self.keys_file, clock=self.clock, mono=lambda: self.true_ms / 1000,
                                   log=lambda text: log(self.out, "keeper.log.jsonl", t=self.clock(), text=text))
        self.silent = {"pi5": False, "pi5b": False}
        self.wrong = {"pi5": False, "pi5b": False}
        self.n_ev = 0
        self.armed = False
        self.visit = None            # (start_s, end_s) of the judge on the spot
        self.next_visit = self.rng.uniform(60, 240)
        self.stored = {"witness": 0, "witness_bad": 0, "witness_silent": 0, "witness_back": 0}
        self.verify_log = []

    def clock(self) -> int:
        return self.true_ms + self.offset_ms

    def event(self, kind, **info):
        self.n_ev += 1
        self.store.add({"v": 2, "type": "event", "t": self.clock(), "kind": kind, "id": f"e{self.n_ev}",
                        "src": "live", "info": info})

    def second(self, s):
        """One simulated second: the judge, the summary, the events."""
        present, motion = False, None
        if self.visit is None and s >= self.next_visit:
            self.visit = (s, s + self.rng.uniform(10, 60))
            self.event("enter", zone=1)
            if self.armed:
                self.event("intrusion", zone=1)
        if self.visit:
            if s >= self.visit[1]:
                self.event("exit", zone=1, stayed_s=round(self.visit[1] - self.visit[0]))
                self.visit = None
                self.next_visit = s + self.rng.uniform(120, 360)
            else:
                present, motion = True, "moving" if s - self.visit[0] < 4 else "still"
        if self.rng.random() < 1 / 300:
            self.event("passed_by", zone=1)
        if s % 1800 == 600:
            self.armed = True
            self.event("armed")
        if s % 1800 == 1200:
            self.armed = False
            self.event("disarmed")
        st = dict(STATE, t=self.clock() + self.rng.randint(0, 99), armed=self.armed,
                  pred={"present": present, "kind": "person" if present else None, "zone": 1 if present else 0,
                        "zone_set": [1] if present else [], "motion": motion,
                        "still_s": (s - self.visit[0] - 4) if present and motion == "still" else 0.0})
        self.store.add(st)

    def witnesses(self):
        msg = self.keeper.publish()
        if msg["seq"] == 0:
            return
        from board import chain
        for node in ("pi5", "pi5b"):
            if self.silent[node]:
                continue
            key = self.wrong_key if self.wrong[node] else self.key[node]
            sig = sign(key, chain.signed_bytes(node, msg["seq"], msg["hash"], msg["t"]), self.tmp)
            kind = self.keeper.on_witness({"v": 2, "type": "chain_witness", "t": msg["t"], "seq": msg["seq"],
                                           "src": "live", "node": node, "hash": msg["hash"], "sig": sig})
            if kind in self.stored:
                self.stored[kind] += 1

    def checkpoint(self, s):
        from agent import ask as agent_ask
        st = self.store
        size = sum(Path(str(self.db_path) + x).stat().st_size for x in ("", "-wal") if Path(str(self.db_path) + x).exists())
        status, status_ms = timed(self.keeper.status)
        _, tail_ms = timed(lambda: st.tail(40))
        _, tail200_ms = timed(lambda: st.tail(200))
        v3600, v3600_ms = timed(lambda: st.verify(), 1)
        bg = self.verify_log[-1] if self.verify_log else None
        asks = {}
        for label, q in (("5min", "what happened in the last five minutes?"), ("30min", "what happened in the last 30 minutes?")):
            reply, ms = timed(lambda: agent_ask.ask(q, st, llm=None, now_ms=self.clock()), 1)
            asks[label] = {"ms": ms, "tool": reply.get("tool"), "chain_ok": reply.get("chain_ok"),
                           "cites": len(reply.get("cites") or []), "answer": reply.get("answer", "")[:160],
                           "verify_rows": next((x["rows"] for x in reply.get("steps", []) if x["tool"] == "verify the chain"), None)}
        rec = {"sim_h": round(s / 3600, 2), "records": status["records"], "head": status["head"]["seq"],
               "first_seq": status["first_seq"], "anchor": status["anchor"], "bytes": size,
               "bytes_per_record": round(size / max(1, status["records"]), 1),
               "status_ms": status_ms, "tail40_ms": tail_ms, "tail200_ms": tail200_ms,
               "verify3600_ms": v3600_ms, "verify3600_ok": v3600["ok"],
               "bg_verify": bg, "verified": status["verified"],
               "witnesses": status["witnesses"], "ask": asks, "rss_mb": rss_mb(), "stored": dict(self.stored),
               "offset_h": round(self.offset_ms / 3_600_000, 2)}
        if self.a.full_verify_every and (s // 1800) % self.a.full_verify_every == 0:
            rec["full_verify"] = full_verify(st)
            rec["contiguous"] = contiguous(self.db_path)
        log(self.out, "checkpoints.jsonl", **rec)
        print(json.dumps({k: rec[k] for k in ("sim_h", "records", "bytes", "status_ms", "verified")}
                         | {"bg_ms": bg and bg["ms"], "bg_checked": bg and bg["checked"],
                            "ask5": asks["5min"]["ms"], "ask30": asks["30min"]["ms"]}), flush=True)

    def schedule(self, s):
        """--faults: the witness and clock faults, at fixed simulated hours."""
        h = s / 3600
        F = [(1.0, 1.1667, "silent_pi5b"), (2.0, 2.1667, "wrong_pi5"), (3.0, 3.1667, "both_gone"),
             (4.0, 4.3333, "clock_back_1h"), (5.0, 5.1667, "clock_fwd_2d")]
        active = {name for a, b, name in F if a <= h < b}
        self.silent["pi5b"] = "silent_pi5b" in active or "both_gone" in active
        self.silent["pi5"] = "both_gone" in active
        self.wrong["pi5"] = "wrong_pi5" in active
        off = -3_600_000 if "clock_back_1h" in active else 172_800_000 if "clock_fwd_2d" in active else 0
        if off != self.offset_ms:
            log(self.out, "faults.jsonl", sim_h=round(h, 3), offset_ms_from=self.offset_ms, offset_ms_to=off,
                head=self.store.head()["seq"], records=self.store.chain_info()["records"],
                contiguous=contiguous(self.db_path))
            self.offset_ms = off
        prev = getattr(self, "_active", set())
        for name in active ^ prev:
            log(self.out, "faults.jsonl", sim_h=round(h, 3), fault=name, on=name in active,
                stored=dict(self.stored), verify=self.verify_log[-1] if self.verify_log else None,
                chain_records=self.store.chain_info()["records"], witnesses=self.keeper.status()["witnesses"])
        self._active = active

    def run(self):
        total = int(self.a.hours * 3600)
        t0 = time.time()
        for s in range(total):
            if self.a.faults:
                self.schedule(s)
            self.second(s)
            self.keeper.tick()
            if s % 5 == 0:
                self.witnesses()
            if s % 30 == 0:
                r = self.keeper.verify_now()
                self.verify_log.append({"sim_h": round(s / 3600, 3), "ms": r["ms"], "checked": r["checked"], "ok": r["ok"]})
                log(self.out, "bg_verify.jsonl", **self.verify_log[-1])
                if not r["ok"]:
                    log(self.out, "problems.jsonl", kind="bg_verify_failed", sim_h=round(s / 3600, 3), result=r)
            if s % 1800 == 0 or s == total - 1:
                self.checkpoint(s)
            self.true_ms += 1000
        end = {"hours": self.a.hours, "wall_s": round(time.time() - t0), "full_verify": full_verify(self.store),
               "contiguous": contiguous(self.db_path), "stored": self.stored, "rss_mb": rss_mb(),
               "chain": self.keeper.status()}
        # a restart: a new store and keeper on the same file
        self.store.close()
        from store import Store
        from board import chain
        again = Store(self.db_path, keep_h=self.a.keep_h)
        k2 = chain.Keeper(again, self.keys_file, clock=self.clock, mono=lambda: self.true_ms / 1000)
        end["after_restart"] = {"full_verify": full_verify(again), "head": again.head(), "status": k2.status(),
                                "verify_now": k2.verify_now()}
        again.close()
        json.dump(end, open(self.out / "summary.json", "w"), indent=1, default=str)
        print(json.dumps(end, default=str)[:3000], flush=True)


# ---------------------------------------------------------------- prune and restart

def cmd_prune(a):
    """A store kept for 1 h, written for 3.5 h with restarts between prunes: does the chain still verify
    from its anchor, does the anchor hold across restarts, and what does the detective say over a pruned edge."""
    a.hours, a.keep_h, a.faults, a.full_verify_every = 3.5, 1.0, False, 1
    d = SimDay(a)
    out = []
    for leg in range(4):
        total = int(a.hours * 3600 / 4)
        for s in range(total):
            d.second(s + leg * total)
            d.keeper.tick()
            if s % 5 == 0:
                d.witnesses()
            d.true_ms += 1000
        from store import Store
        from board import chain
        before = d.store.chain_info()
        d.store.close()
        d.store = Store(d.db_path, keep_h=a.keep_h)
        d.keeper = chain.Keeper(d.store, d.keys_file, clock=d.clock, mono=lambda: d.true_ms / 1000)
        after = d.store.chain_info()
        from agent import ask as agent_ask
        q = agent_ask.ask("what happened in the last two hours?", d.store, llm=None, now_ms=d.clock())
        rec = {"leg": leg, "before": before, "after_restart": after, "same_head": before["head"] == after["head"],
               "same_anchor": before["anchor"] == after["anchor"], "full_verify": full_verify(d.store),
               "verify_now": d.keeper.verify_now(), "contiguous": contiguous(d.db_path),
               "ask_2h": {"chain_ok": q.get("chain_ok"), "answer": q["answer"][:200], "cites": len(q.get("cites") or [])}}
        # the oldest kept record must point at the anchor
        oldest = d.store.records(limit=1)
        rec["oldest_prev_is_anchor"] = bool(oldest) and after["anchor"] is not None and oldest[0]["prev"] == after["anchor"]["hash"]
        log(d.out, "prune.jsonl", **rec)
        print(json.dumps({k: rec[k] for k in ("leg", "same_head", "same_anchor", "oldest_prev_is_anchor")}
                         | {"verify": rec["full_verify"]["ok"], "first": after["first_seq"], "anchor": after["anchor"]}), flush=True)
        out.append(rec)
    json.dump(out, open(d.out / "summary.json", "w"), indent=1, default=str)


# ---------------------------------------------------------------- hard kills and two processes at once

WRITER = r'''
import json, os, random, sys, time
sys.path.insert(0, sys.argv[1])
db, role, start_at = sys.argv[2], sys.argv[3], float(sys.argv[4])
while time.time() < start_at:
    time.sleep(0.0005)
from store import Store
from store.__main__ import Keeper
errors = []
try:
    st = Store(db)
except Exception as e:
    print("OPEN-ERROR", role, repr(e), flush=True); sys.exit(3)
print("OPENED", role, flush=True)
k = Keeper(st, log=lambda text: print("KEEPER", role, text, flush=True))
t = int(time.time() * 1000) + (0 if role == "store" else 500)
n = 0
while True:
    n += 1
    t += 1000
    try:
        if role == "store":
            k.keep(json.dumps({"v": 2, "type": "state", "t": t, "src": "live", "pred": None, "health": {"status": "ok"},
                               "alert": {}, "links": [], "armed": False}))
            if n % 7 == 0:
                k.keep(json.dumps({"v": 2, "type": "event", "t": t + 1, "kind": "enter", "id": f"{os.getpid()}-{n}",
                                   "src": "live", "info": {"zone": 1}}))
        else:
            st.append("witness", {"node": "pi5", "seq": n, "hash": "0" * 64, "t": t, "sig": "x"}, t)
    except Exception as e:
        print("WRITE-ERROR", role, repr(e), flush=True)
        time.sleep(0.05)
    time.sleep(0.001)
'''

OLD_SCHEMA = """
create table events(n integer primary key, t integer not null, kind text not null, id text, src text,
    info text not null, unique(id, t));
create index events_t on events(t);
create table seconds(t int primary key, src text, present integer, kind text, zone integer, motion text, still_s real,
    health text, blind text not null, alert text, alert_zone integer, armed integer not null, cam text, router text,
    links text not null, advice text, model text);
insert into seconds(t, blind, armed, links) values (1, '[]', 0, '{}'), (2, '[]', 0, '{}');
insert into events(t, kind, id, src, info) values (1, 'enter', 'a', 'live', '{}');
"""


def spawn(a, db, role, start_at, logf):
    """A writer whose output goes through a pipe (like journald), so a full disk can't stop it saying why."""
    import threading
    p = subprocess.Popen([sys.executable, "-c", WRITER, str(REPO), str(db), role, str(start_at)],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def copy():
        for raw in iter(p.stdout.readline, b""):
            logf.write(raw.decode("utf-8", "replace"))
            logf.flush()
        logf.write(f"EXIT {role} {p.wait()}\n")
        logf.flush()
    threading.Thread(target=copy, daemon=True).start()
    return p


def cmd_kill(a):
    """Two writers on one file (the store's Keeper, and the web server's witness records); one or both
    killed with SIGKILL at a random moment mid-write, restarted together. After each round the file is
    checked: quick_check, no gap or duplicate in seq, the whole chain verifies."""
    from store import Store
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    db = out / "kill.db"
    rng = random.Random(a.seed)
    logf = open(out / "writers.log", "a")
    procs = {r: spawn(a, db, r, time.time(), logf) for r in ("store", "web")}
    bad = 0
    for i in range(a.rounds):
        time.sleep(rng.uniform(0.05, 1.5))
        victims = rng.choice([["store"], ["web"], ["store", "web"]])
        for r in victims:
            procs[r].send_signal(signal.SIGKILL)
            procs[r].wait()
        c = contiguous(db)
        s = Store(db)
        v = full_verify(s)
        s.close()
        ok = c["gapless"] and v["ok"] and not c["dup_seq_events"] and not c["dup_seq_seconds"] and c["quick_check"] == "ok"
        bad += not ok
        log(out, "kill.jsonl", round=i, victims=victims, ok=ok, contiguous=c, verify=v)
        start_at = time.time() + 0.2
        for r in victims:
            procs[r] = spawn(a, db, r, start_at, logf)
    for p in procs.values():
        p.kill()
    logf.close()
    text = (out / "writers.log").read_text()
    summary = {"rounds": a.rounds, "bad_rounds": bad, "write_errors": text.count("WRITE-ERROR"),
               "open_errors": text.count("OPEN-ERROR"), "keeper_drops": text.count("KEEPER"),
               "final": contiguous(db)}
    json.dump(summary, open(out / "summary.json", "w"), indent=1)
    print(json.dumps(summary), flush=True)


def cmd_open2(a):
    """After a restart the store and the web server open the same file at the same moment and write at
    once. Rounds alternate: a file from before the record was sealed, a fresh file, a file in use."""
    from store import Store
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    logf = open(out / "writers.log", "a")
    bad, rounds = 0, []
    db = out / "open2.db"
    for i in range(a.rounds):
        mode = ["old", "fresh", "used"][i % 3]
        if mode in ("old", "fresh"):
            for suffix in ("", "-wal", "-shm"):
                Path(str(db) + suffix).unlink(missing_ok=True)
            if mode == "old":
                c = sqlite3.connect(db)
                c.executescript(OLD_SCHEMA)
                c.close()
        mark = (out / "writers.log").stat().st_size if (out / "writers.log").exists() else 0
        start_at = time.time() + 0.5
        procs = [spawn(a, db, r, start_at, logf) for r in ("store", "web")]
        time.sleep(3.0)
        alive = [p.poll() is None for p in procs]
        for p in procs:
            p.send_signal(signal.SIGKILL)
            p.wait()
        logf.flush()
        text = (out / "writers.log").read_text()[mark:]
        c = contiguous(db)
        s = Store(db)
        v = full_verify(s)
        info = s.chain_info()
        s.close()
        ok = all(alive) and "ERROR" not in text and c["gapless"] and v["ok"] and c["quick_check"] == "ok"
        bad += not ok
        rec = {"round": i, "mode": mode, "ok": ok, "alive": alive, "errors": [l for l in text.splitlines() if "ERROR" in l][:5],
               "contiguous": c, "verify": v, "unsealed": info["unsealed"]}
        rounds.append(rec)
        log(out, "open2.jsonl", **rec)
    logf.close()
    summary = {"rounds": a.rounds, "bad_rounds": bad,
               "bad_by_mode": {m: sum(1 for r in rounds if r["mode"] == m and not r["ok"]) for m in ("old", "fresh", "used")},
               "first_errors": [r["errors"] for r in rounds if r["errors"]][:5]}
    json.dump(summary, open(out / "summary.json", "w"), indent=1)
    print(json.dumps(summary), flush=True)


def cmd_disk(a):
    """A full disk (RLIMIT_FSIZE on both writers, as day.py does) for 20-90 s, eight times, while both write;
    then: does each writer write again by itself, is the chain gapless and does it verify."""
    import psutil
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    db = out / "disk.db"
    rng = random.Random(a.seed)
    logf = open(out / "writers.log", "a")
    procs = {r: spawn(a, db, r, time.time(), logf) for r in ("store", "web")}
    from store import Store
    for i in range(a.rounds):
        time.sleep(rng.uniform(5, 20))
        size0 = db.stat().st_size
        secs = rng.uniform(20, 90)
        for p in procs.values():
            psutil.Process(p.pid).rlimit(psutil.RLIMIT_FSIZE, (1, psutil.RLIM_INFINITY))
        time.sleep(secs)
        head_full = contiguous(db)["last"]
        for p in procs.values():
            psutil.Process(p.pid).rlimit(psutil.RLIMIT_FSIZE, (psutil.RLIM_INFINITY, psutil.RLIM_INFINITY))
        time.sleep(10)
        c = contiguous(db)
        s = Store(db)
        v = full_verify(s)
        s.close()
        alive = {r: p.poll() is None for r, p in procs.items()}
        rec = {"exit": {r: p.poll() for r, p in procs.items()}, "round": i, "full_s": round(secs), "size0": size0, "head_during": head_full, "head_after": c["last"],
               "writes_again": c["last"] > head_full, "alive": alive, "contiguous": c, "verify": v}
        log(out, "disk.jsonl", **rec)
        print(json.dumps({k: rec[k] for k in ("round", "full_s", "writes_again", "alive")} | {"ok": v["ok"], "gapless": c["gapless"]}), flush=True)
        for r, p in procs.items():
            if p.poll() is not None:
                procs[r] = spawn(a, db, r, time.time(), logf)
    for p in procs.values():
        p.kill()
    logf.close()
    text = (out / "writers.log").read_text()
    summary = {"rounds": a.rounds, "write_errors": text.count("WRITE-ERROR"), "keeper_lines": text.count("KEEPER"),
               "final": contiguous(db), "sample_errors": sorted({l[:160] for l in text.splitlines() if "ERROR" in l})[:8]}
    json.dump(summary, open(out / "summary.json", "w"), indent=1)
    print(json.dumps(summary), flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("mode", choices=("day", "prune", "kill", "open2", "disk"))
    ap.add_argument("--hours", type=float, default=8.0)
    ap.add_argument("--keep-h", type=float, default=24.0)
    ap.add_argument("--faults", action="store_true")
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--rounds", type=int, default=60)
    ap.add_argument("--full-verify-every", type=int, default=2, help="checkpoints (of 30 min) between full verifies")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.mode == "day":
        SimDay(a).run()
    else:
        {"prune": cmd_prune, "kill": cmd_kill, "open2": cmd_open2, "disk": cmd_disk}[a.mode](a)


if __name__ == "__main__":
    main()
