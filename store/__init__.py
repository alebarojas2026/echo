"""The room's records on the board: every event, and one summary of state a second.

    python -m store                      # follow the brain at ws://127.0.0.1:8765/ws
    python -m store --sim demo           # fill from a simulated path instead (src "sim")

One SQLite file, data/sessions/store.db by default (git-ignored, never leaves the board).
It holds what the brain already sends to the screen (CONTRACTS.md section 5): no radio
readings, no camera labels, no images.

Every row saved is also one link of the sealed record (CONTRACTS.md section 13, store/chain.py): the
chain table holds {seq, t, kind, body, prev, hash} for each, in the order they were saved, and the
events and seconds rows carry their seq. Rows saved before this existed stay as they are, with no
seq: the chain starts at the first row saved after it. The head is read from the file inside the
same transaction that adds a link, so the chain carries on over a restart, and a second process
(the web server, adding the witnesses' signatures) can add links too. Order is seq, never t: the
board's clock can be stepped.
"""
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path

from .chain import ZERO, alter, canon, record_hash, timed, verify_rows

DB = Path(__file__).resolve().parent.parent / "data" / "sessions" / "store.db"
KEEP_H = 24.0          # older rows are dropped
PRUNE_EVERY = 600      # saved seconds between prunes

SCHEMA = """
create table if not exists events(
    n integer primary key, t integer not null, kind text not null, id text, src text,
    info text not null, seq integer, unique(id, t));
create index if not exists events_t on events(t);
create table if not exists seconds(
    t int primary key, src text,
    present integer, kind text, zone integer, motion text, still_s real,
    health text, blind text not null, alert text, alert_zone integer, armed integer not null,
    cam text, router text, links text not null, advice text, model text,
    zone_set text, tamper text, seq integer);
create table if not exists chain(
    seq integer primary key, t integer not null, kind text not null, body text not null,
    prev text not null, hash text not null);
create index if not exists chain_t on chain(t);
create table if not exists chain_meta(k text primary key, v text not null);
"""
ADDED = ("zone_set", "tamper")   # columns newer than the first store files: added to an old file on open
MAX_HISTORY_MS = 30 * 60_000
JSON_COLUMNS = ("blind", "links", "advice", "model", "zone_set", "tamper")
VERIFY_DEFAULT = 3600      # records checked by verify() when no start is named
VERIFY_MAX = 100_000       # most records checked in one call
PROVE_DEFAULT, PROVE_MAX = 600, 3600
ROW = "seq, t, kind, body, prev, hash"


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
        for table in ("events", "seconds"):   # a file from before the record was sealed
            if "seq" not in {r["name"] for r in self.db.execute(f"pragma table_info({table})")}:
                self.db.execute(f"alter table {table} add column seq integer")
        # INTEGER PRIMARY KEY aliases rowid; INT keeps insertion order separate from time.
        columns = list(self.db.execute("pragma table_info(seconds)"))
        if any(c["name"] == "t" and c["type"].upper() == "INTEGER" for c in columns):
            with self.db:
                create = SCHEMA.split("create table if not exists seconds", 1)[1].split(";", 1)[0]
                self.db.execute("create table seconds_new" + create)
                names = ", ".join(c["name"] for c in columns)
                self.db.execute(f"insert into seconds_new({names}) select {names} from seconds order by t")
                self.db.execute("drop table seconds")
                self.db.execute("alter table seconds_new rename to seconds")
        self.lock, self._saved = threading.Lock(), 0

    def add(self, msg: dict) -> bool:
        """Save a brain message. True if a row was written: every event, and the first state
        of each second."""
        if not isinstance(msg, dict) or not isinstance(msg.get("t"), int):
            return False
        if msg.get("type") not in ("event", "state"):
            return False
        with self.lock, self.db:
            self._begin()   # the head is read and the link added as one step
            if msg.get("type") == "event" and isinstance(msg.get("kind"), str):
                info = msg.get("info") or {}
                cur = self.db.execute(
                    "insert or ignore into events(t, kind, id, src, info) values (?,?,?,?,?)",
                    (msg["t"], msg["kind"], msg.get("id"), msg.get("src"), json.dumps(info)))
                if cur.rowcount != 1:
                    return False
                seq = self._seal(msg["t"], msg["kind"], {"id": msg.get("id"), "src": msg.get("src"), "info": info})
                self.db.execute("update events set seq = ? where n = ?", (seq, cur.lastrowid))
                return True
            if msg.get("type") != "state":
                return False
            row = summary(msg)
            newest = self.db.execute("select t from seconds order by rowid desc limit 1").fetchone()
            if newest and newest["t"] == row["t"]:
                return False
            if newest and row["t"] < newest["t"] - 5000:
                logging.getLogger(__name__).warning("Board clock moved backwards: %s -> %s", newest["t"], row["t"])
            body = {k: json.loads(v) if k in JSON_COLUMNS and v else v for k, v in row.items() if k != "t"}
            row["seq"] = self._seal(row["t"], "second", body)
            cur = self.db.execute(
                f"insert or replace into seconds({', '.join(row)}) values ({', '.join('?' * len(row))})",
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
        # The chain loses its oldest links only, never one from the middle, and never its head. The
        # last link dropped stays as the anchor: the oldest kept link's prev is its hash.
        keep = self.db.execute("select min(seq) from chain where t >= ?", (now_ms - self.keep_ms,)).fetchone()[0]
        if keep is None:
            keep = self.db.execute("select max(seq) from chain").fetchone()[0]
        last = keep and self.db.execute("select seq, hash, t from chain where seq = ?", (keep - 1,)).fetchone()
        if last:
            self._meta("anchor", {"seq": last["seq"], "hash": last["hash"], "t": last["t"], "pruned_t": now_ms})
            self.db.execute("delete from chain where seq < ?", (keep,))

    # ---- the sealed record (CONTRACTS.md section 13) ----

    def _meta(self, key: str, value=None):
        if value is not None:
            self.db.execute("insert or replace into chain_meta(k, v) values (?, ?)", (key, json.dumps(value)))
            return value
        r = self.db.execute("select v from chain_meta where k = ?", (key,)).fetchone()
        return json.loads(r["v"]) if r else None

    def _begin(self) -> None:
        """Take the write lock now, so no other process adds a link between reading the head and writing."""
        if not self.db.in_transaction:
            self.db.execute("begin immediate")

    def _head(self):
        """(seq, hash) of the newest link; after a prune that left nothing, the anchor; else (0, zeros)."""
        r = self.db.execute("select seq, hash from chain order by seq desc limit 1").fetchone()
        if r:
            return r["seq"], r["hash"]
        anchor = self._meta("anchor")
        return (anchor["seq"], anchor["hash"]) if anchor else (0, ZERO)

    def _seal(self, t: int, kind: str, body: dict) -> int:
        """Add one link inside the open transaction; returns its seq."""
        last, prev = self._head()
        text = canon(body)
        self.db.execute(f"insert into chain({ROW}) values (?,?,?,?,?,?)",
                        (last + 1, t, kind, text, prev, record_hash(last + 1, t, kind, text, prev)))
        return last + 1

    def append(self, kind: str, body: dict, t: int) -> dict:
        """Add a record that is neither an event nor a second (a witness's signature, a witness gone
        silent). Returns it as records() would."""
        with self.lock, self.db:
            self._begin()
            seq = self._seal(t, kind, body)
        return self.records(seq, seq)[0]

    def head(self) -> dict:
        with self.lock:
            seq, digest = self._head()
        return {"seq": seq, "hash": digest}

    def chain_info(self) -> dict:
        """What GET /chain says about the log itself: head, records, since_t, first_seq, anchor, unsealed."""
        with self.lock:
            seq, digest = self._head()
            n, first = self.db.execute("select count(*), min(seq) from chain").fetchone()
            since = self.db.execute("select t from chain where seq = ?", (first,)).fetchone() if first else None
            anchor = self._meta("anchor")
            old = sum(self.db.execute(f"select count(*) from {table} where seq is null").fetchone()[0]
                      for table in ("events", "seconds"))
        return {"head": {"seq": seq, "hash": digest}, "records": n, "since_t": since["t"] if since else None,
                "first_seq": first, "anchor": anchor and {"seq": anchor["seq"], "hash": anchor["hash"]},
                "unsealed": old}

    def _before(self, seq: int):
        """The hash the link `seq` must point at, or None when the link before it is gone and is not
        the anchor (links were removed)."""
        if seq == 1:
            return ZERO
        r = self.db.execute("select hash from chain where seq = ?", (seq - 1,)).fetchone()
        if r:
            return r["hash"]
        anchor = self._meta("anchor")
        return anchor["hash"] if anchor and anchor["seq"] == seq - 1 else None

    def _range(self, from_seq, to_seq):
        """The links from from_seq to to_seq as (rows, the hash before the first, from, to), clamped to
        what is kept. Without from_seq: the VERIFY_DEFAULT links up to to_seq."""
        with self.lock:
            first, last = self.db.execute("select min(seq), max(seq) from chain").fetchone()
            if first is None:
                return [], ZERO, None, None
            to_seq = last if to_seq is None else min(to_seq, last)
            from_seq = max(first, to_seq - VERIFY_DEFAULT + 1 if from_seq is None else from_seq)
            if to_seq - from_seq >= VERIFY_MAX:
                raise ValueError(f"at most {VERIFY_MAX} records per check; ask for a shorter range")
            rows = [tuple(r) for r in self.db.execute(
                f"select {ROW} from chain where seq between ? and ? order by seq", (from_seq, to_seq))]
            return rows, self._before(from_seq), from_seq, to_seq

    def verify(self, from_seq=None, to_seq=None) -> dict:
        """Walk the chain from from_seq to to_seq and name the first bad record:
        {"ok", "checked", "first_bad_seq", "ms", "from", "to"} (GET /chain/verify). ms is the whole call, the read from the file
        included. Reads only."""
        start = time.perf_counter()
        rows, before, from_seq, to_seq = self._range(from_seq, to_seq)
        if rows and before is None:              # the link before the first is missing
            ok, checked, bad = False, 0, from_seq - 1
        else:
            ok, checked, bad = verify_rows(rows, before)
        return {"ok": ok, "checked": checked, "first_bad_seq": bad, "ms": round((time.perf_counter() - start) * 1000, 1),
                "from": from_seq, "to": to_seq}

    def verify_since(self, since_ms: int) -> dict:
        """verify() from the first record saved at or after since_ms (by its own t) to the head."""
        with self.lock:
            first = self.db.execute("select min(seq) from chain where t >= ?", (since_ms,)).fetchone()[0]
            last = self.db.execute("select max(seq) from chain").fetchone()[0]
        if first is None:
            first = last
        if last is not None and last - first >= VERIFY_MAX:
            first = last - VERIFY_MAX + 1
        return self.verify(first, last)

    def prove(self, n: int = PROVE_DEFAULT, seq=None) -> dict:
        """The prove-it check (POST /chain/prove): copy the last n links into memory, alter one link
        of the copy (seq, or the one in the middle), check the copy and name the record. The log
        itself is only read. ValueError when there is no record, or seq is not among the last n."""
        n = max(1, min(int(n), PROVE_MAX))
        with self.lock:
            last = self.db.execute("select max(seq) from chain").fetchone()[0]
        if last is None:
            raise ValueError("no sealed record yet")
        rows, before, from_seq, to_seq = self._range(last - n + 1, last)
        copy = list(rows)
        at = len(copy) // 2 if seq is None else seq - from_seq
        if not 0 <= at < len(copy):
            raise ValueError(f"record {seq} is not among the last {len(copy)} records")
        copy[at] = alter(copy[at])
        out = timed(lambda: verify_rows(copy, before))
        return {"ok": out["ok"], "altered_seq": copy[at][0], "first_bad_seq": out["first_bad_seq"], "ms": out["ms"],
                "checked": len(copy), "kind": copy[at][2], "t": copy[at][1]}

    def records(self, from_seq=None, to_seq=None, kinds=None, since_ms=None, until_ms=None, limit: int = 1000,
                newest: bool = False) -> list:
        """Sealed records as {"seq", "t", "kind", "body", "prev", "hash"}, oldest first, at most limit
        of them: the first `limit` of the range, or with newest=True the last `limit`."""
        q, args = [], []
        for clause, value in (("seq >= ?", from_seq), ("seq <= ?", to_seq), ("t >= ?", since_ms), ("t <= ?", until_ms)):
            if value is not None:
                q.append(clause)
                args.append(value)
        if kinds:
            q.append(f"kind in ({', '.join('?' * len(kinds))})")
            args += list(kinds)
        where = f" where {' and '.join(q)}" if q else ""
        with self.lock:
            rows = self.db.execute(f"select {ROW} from chain{where} order by seq {'desc' if newest else 'asc'} limit ?",
                                   [*args, int(limit)]).fetchall()
        out = [{**dict(r), "body": json.loads(r["body"])} for r in rows]
        return out[::-1] if newest else out

    def events(self, since_ms: int = 0, kinds=None) -> list:
        """Events at or after since_ms, oldest first, as dicts with info decoded."""
        q, args = "select t, kind, id, src, info, seq from events where t >= ?", [since_ms]
        if kinds:
            q += f" and kind in ({', '.join('?' * len(kinds))})"
            args += list(kinds)
        with self.lock:
            rows = self.db.execute(q + " order by t, n", args).fetchall()
        return [{**dict(r), "info": json.loads(r["info"])} for r in rows]

    def seconds(self, since_ms: int = 0, until_ms=None) -> list:
        """Saved seconds at or after since_ms, oldest first, with the JSON columns decoded."""
        with self.lock:
            query, args = "select * from seconds where t >= ?", [since_ms]
            if until_ms is not None:
                query += " and t <= ?"
                args.append(until_ms)
            rows = self.db.execute(query + " order by t", args).fetchall()
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
        for r in self.seconds(from_t, to_t):
            known = r["present"] is not None
            rows.append({"t": r["t"], "present": bool(r["present"]) if known else None,
                         "zone": r["zone"] if known else None, "zone_set": r["zone_set"] if r["present"] else [],
                         "motion": r["motion"] if r["present"] else None, "armed": bool(r["armed"]),
                         "alert": r["alert"] == "check_on", "health": r["health"], "tamper": r["tamper"]})
        return {"from_t": from_t, "to_t": to_t, "step_s": 1, "rows": rows}

    def latest(self):
        """The newest saved second, or None when the store is empty."""
        with self.lock:
            r = self.db.execute("select t from seconds order by rowid desc limit 1").fetchone()
        return None if r is None else self.seconds(r["t"], r["t"])[0]

    def close(self) -> None:
        self.db.close()
