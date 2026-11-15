"""The sealed record (CONTRACTS.md section 13): how a record is hashed, and how a run of them is checked.

Every record the store saves is one link: {seq, t, kind, body, prev, hash}. hash is SHA-256 of the
canonical JSON of {seq, t, kind, body, prev} (sorted keys, no spaces, UTF-8), and prev is the hash of
the record before it. Changing any stored record, or removing one, breaks the chain at that record.

Nothing here touches the database: verify_rows() takes rows, so the same check runs on the real log
and on an altered copy held in memory (the prove-it check).
"""
import hashlib
import json
import time

ZERO = "0" * 64   # prev of the first record


def canon(obj) -> str:
    """Canonical JSON: sorted keys, no spaces, characters as themselves."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def record_hash(seq: int, t: int, kind: str, body: str, prev: str) -> str:
    """The hash of one record. body is its canonical JSON text, as the store keeps it, so the
    canonical JSON of the whole record is put together without parsing it again (the keys are
    already in order: body, kind, prev, seq, t)."""
    text = f'{{"body":{body},"kind":{json.dumps(kind, ensure_ascii=False)},"prev":"{prev}","seq":{seq},"t":{t}}}'
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def verify_rows(rows, prev=None):
    """Check rows (seq, t, kind, body text, prev, hash), oldest first. prev: the hash the first row
    must point at, or None when that is not known. Returns (ok, checked, first_bad_seq): a record is
    bad when its hash is not the hash of its own fields, when its prev is not the hash before it,
    or when a seq is missing (then the missing seq is named)."""
    checked, expect = 0, None
    for seq, t, kind, body, row_prev, row_hash in rows:
        checked += 1
        if expect is not None and seq != expect:
            return False, checked, expect
        if (prev is not None and row_prev != prev) or record_hash(seq, t, kind, body, row_prev) != row_hash:
            return False, checked, seq
        prev, expect = row_hash, seq + 1
    return True, checked, None


def timed(check) -> dict:
    """Run check() -> (ok, checked, first_bad_seq) and give the answer of GET /chain/verify."""
    start = time.perf_counter()
    ok, checked, bad = check()
    return {"ok": ok, "checked": checked, "first_bad_seq": bad, "ms": round((time.perf_counter() - start) * 1000, 1)}


def alter(row):
    """A copy of one row with its body changed and its hash left as it was: what an edit of the
    stored record would look like."""
    seq, t, kind, body, prev, row_hash = row
    return (seq, t, kind, canon({**json.loads(body), "altered": True}), prev, row_hash)
