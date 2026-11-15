"""The room's records on the board: every event, and one summary of state a second.

    python -m store                      # follow the brain at ws://127.0.0.1:8765/ws
    python -m store --sim demo           # fill from a simulated path instead (src "sim")

One SQLite file, data/sessions/store.db by default (git-ignored, never leaves the board).
It holds what the brain already sends to the screen (CONTRACTS.md section 5): no radio
readings, no camera labels, no images.
"""
import json
import sqlite3
import threading
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "sessions" / "store.db"
KEEP_H = 24.0          # older rows are dropped
PRUNE_EVERY = 600      # saved seconds between prunes

SCHEMA = """
create table if not exists events(
    n integer primary key, t integer not null, kind text not null, id text, src text,
    info text not null, unique(id, t));
create index if not exists events_t on events(t);
create table if not exists seconds(
    t integer primary key, src text,
    present integer, kind text, zone integer, motion text, still_s real,
    health text, blind text not null, alert text, alert_zone integer, armed integer not null,
    cam text, router text, links text not null, advice text, model text,
    zone_set text, tamper text);
"""
ADDED = ("zone_set", "tamper")   # columns newer than the first store files: added to an old file on open
MAX_HISTORY_MS = 30 * 60_000


def summary(state: dict) -> dict:
    """One `state` message as a `seconds` row. present is None when there is no prediction
    (before training, sensor blind, recalibrating): unknown, never "nobody"."""
    pred, alert = state.get("pred"), state.get("alert") or {}
    health = state.get("health") or {}
    links = {l["id"]: {"dbm": l.get("dbm"), "drop_db": l.get("drop_db"), "status": l.get("status")}
             for l in state.get("links") or []}
    return {
        "t": state["t"] // 1000 * 1000, "src": state.get("src"),
        "present": None if pred is None else int(bool(pred.get("present"))),
        "kind": pred and pred.get("kind"), "zone": pred and pred.get("zone"),
        "motion": pred and pred.get("motion"), "still_s": pred and pred.get("still_s"),
        "health": health.get("status"), "blind": json.dumps(health.get("blind") or []),
        "alert": alert.get("state"), "alert_zone": alert.get("zone"),
        "armed": int(bool(state.get("armed"))), "cam": state.get("cam"), "router": state.get("router"),
        "links": json.dumps(links),
        "advice": json.dumps(state["advice"]) if state.get("advice") else None,
        "model": json.dumps(state["model"]) if state.get("model") else None,
        "zone_set": json.dumps((pred and pred.get("zone_set")) or []),
        "tamper": json.dumps(state.get("tamper") or []),
    }


class Store:
    def __init__(self, path=DB, keep_h: float = KEEP_H):
        self.keep_ms = int(keep_h * 3_600_000)
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        if str(path) != ":memory:":
            self.db.execute("pragma journal_mode=wal")   # the agent reads while this writes
        self.db.executescript(SCHEMA)
        have = {r["name"] for r in self.db.execute("pragma table_info(seconds)")}
        for column in ADDED:
            if column not in have:
                self.db.execute(f"alter table seconds add column {column} text")
        self.lock, self._saved = threading.Lock(), 0

    def add(self, msg: dict) -> bool:
        """Save a brain message. True if a row was written: every event, and the first state
        of each second."""
        if not isinstance(msg, dict) or not isinstance(msg.get("t"), int):
            return False
        with self.lock, self.db:
            if msg.get("type") == "event" and isinstance(msg.get("kind"), str):
                cur = self.db.execute(
                    "insert or ignore into events(t, kind, id, src, info) values (?,?,?,?,?)",
                    (msg["t"], msg["kind"], msg.get("id"), msg.get("src"), json.dumps(msg.get("info") or {})))
                return cur.rowcount == 1
            if msg.get("type") != "state":
                return False
            row = summary(msg)
            cur = self.db.execute(
                f"insert or ignore into seconds({', '.join(row)}) values ({', '.join('?' * len(row))})",
                tuple(row.values()))
            if cur.rowcount != 1:
                return False
            self._saved += 1
            if self._saved % PRUNE_EVERY == 0:
                self.prune(row["t"])
            return True

    def prune(self, now_ms: int) -> None:
        for table in ("events", "seconds"):
            self.db.execute(f"delete from {table} where t < ?", (now_ms - self.keep_ms,))

    def events(self, since_ms: int = 0, kinds=None) -> list:
        """Events at or after since_ms, oldest first, as dicts with info decoded."""
        q, args = "select t, kind, id, src, info from events where t >= ?", [since_ms]
        if kinds:
            q += f" and kind in ({', '.join('?' * len(kinds))})"
            args += list(kinds)
        with self.lock:
            rows = self.db.execute(q + " order by t, n", args).fetchall()
        return [{**dict(r), "info": json.loads(r["info"])} for r in rows]

    def seconds(self, since_ms: int = 0) -> list:
        """Saved seconds at or after since_ms, oldest first, with the JSON columns decoded."""
        with self.lock:
            rows = self.db.execute("select * from seconds where t >= ? order by t", (since_ms,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for k in ("blind", "links", "advice", "model"):
                d[k] = json.loads(d[k]) if d[k] else None
            for k in ADDED:
                d[k] = json.loads(d[k]) if d[k] else []
            out.append(d)
        return out

    def history(self, from_t: int, to_t: int) -> dict:
        """CONTRACTS.md section 10, GET /history: the saved seconds from from_t to to_t, exactly as
        saved. A second with no row is missing, and present stays None where the brain did not know.
        ValueError (with a plain message) for a stretch that is backwards or longer than 30 minutes."""
        if to_t < from_t:
            raise ValueError("to_t is before from_t")
        if to_t - from_t > MAX_HISTORY_MS:
            raise ValueError("at most 30 minutes of history per call; ask for a shorter stretch")
        rows = []
        for r in self.seconds(from_t):
            if r["t"] > to_t:
                break
            known = r["present"] is not None
            rows.append({"t": r["t"], "present": bool(r["present"]) if known else None,
                         "zone": r["zone"] if known else None, "zone_set": r["zone_set"] if r["present"] else [],
                         "motion": r["motion"] if r["present"] else None, "armed": bool(r["armed"]),
                         "alert": r["alert"] == "check_on", "health": r["health"], "tamper": r["tamper"]})
        return {"from_t": from_t, "to_t": to_t, "step_s": 1, "rows": rows}

    def latest(self):
        """The newest saved second, or None when the store is empty."""
        with self.lock:
            r = self.db.execute("select max(t) from seconds").fetchone()[0]
        return None if r is None else self.seconds(r)[-1]

    def close(self) -> None:
        self.db.close()
