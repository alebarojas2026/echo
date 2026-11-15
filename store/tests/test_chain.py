"""The sealed record (CONTRACTS.md section 13): every saved row is a link, and a changed one is named."""
import hashlib
import json
import sqlite3
import time

import pytest

from contracts import check
from store import Store
from store.chain import ZERO, canon, record_hash, verify_rows

from .test_store import T0, event, state

OLD_SCHEMA = """
create table events(n integer primary key, t integer not null, kind text not null, id text, src text,
    info text not null, unique(id, t));
create table seconds(t int primary key, src text, present integer, kind text, zone integer, motion text,
    still_s real, health text, blind text not null, alert text, alert_zone integer, armed integer not null,
    cam text, router text, links text not null, advice text, model text, zone_set text, tamper text);
"""


def by_the_contract(r: dict) -> str:
    """The hash as section 13 words it, computed without store/chain.py."""
    link = {k: r[k] for k in ("seq", "t", "kind", "body", "prev")}
    return hashlib.sha256(json.dumps(link, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def filled(s: Store, seconds: int, t0: int = T0) -> Store:
    for i in range(seconds):
        s.add(state(t0 + i * 1000))
    return s


def checked(result: dict) -> dict:
    """A verify answer without its time."""
    return {k: v for k, v in result.items() if k != "ms"}


def dump(s: Store) -> list:
    return [tuple(r) for r in s.db.execute("select * from chain order by seq")]


def test_every_saved_row_is_a_link_hashed_as_the_contract_says():
    s = Store(":memory:")
    assert s.head() == {"seq": 0, "hash": ZERO}
    s.add(state(T0))
    s.add(event(T0 + 200, "enter", id="e1", zone=2))
    s.add(state(T0 + 500))                              # the same second: not saved, so not a link
    s.add(event(T0 + 200, "enter", id="e1", zone=2))    # the same event again: neither
    s.add(state(T0 + 1000, note="café"))
    records = s.records()
    assert [(r["seq"], r["kind"]) for r in records] == [(1, "second"), (2, "enter"), (3, "second")]
    assert records[0]["prev"] == ZERO and [r["prev"] for r in records[1:]] == [r["hash"] for r in records[:-1]]
    assert all(r["hash"] == by_the_contract(r) for r in records)
    assert records[1]["body"] == {"id": "e1", "src": "live", "info": {"zone": 2}}
    assert records[0]["body"]["present"] == 1 and records[0]["body"]["links"]["east>pi5:ble"]["dbm"] == -63.0
    assert "t" not in records[0]["body"]
    assert all(check.errors(r, "record") == [] for r in records)
    assert s.head() == {"seq": 3, "hash": records[-1]["hash"]}
    assert [r["seq"] for r in s.seconds()] == [1, 3] and [e["seq"] for e in s.events()] == [2]
    assert checked(s.verify()) == {"ok": True, "checked": 3, "first_bad_seq": None, "from": 1, "to": 3}


def test_the_fast_hash_is_the_canonical_json_whatever_the_body_holds():
    body = {"z": [1.5, None, True], "a": {"é": "naïve \"q\" \\ \n", "b": -0.0}, "n": 10 ** 20}
    for kind in ("second", "odd \"kind\" é"):
        link = {"seq": 7, "t": T0, "kind": kind, "body": body, "prev": "ab" * 32}
        assert record_hash(7, T0, kind, canon(body), "ab" * 32) == by_the_contract(link)


def test_the_chain_carries_on_over_a_restart(tmp_path):
    path = tmp_path / "store.db"
    s = filled(Store(path), 3)
    head = s.head()
    s.close()
    s = Store(path)
    assert s.head() == head
    s.add(state(T0 + 3000))
    s.add(event(T0 + 3100, "exit", id="e2", zone=2))
    assert [r["seq"] for r in s.records()] == [1, 2, 3, 4, 5] and s.records(4, 4)[0]["prev"] == head["hash"]
    assert s.verify()["ok"] and s.verify()["checked"] == 5


def test_an_older_file_is_left_as_it_was_and_the_chain_starts_at_the_first_new_row(tmp_path):
    path = tmp_path / "store.db"
    db = sqlite3.connect(path)
    db.executescript(OLD_SCHEMA)
    db.execute("insert into events(t, kind, id, src, info) values (?, 'enter', 'old1', 'live', '{}')", (T0 - 9000,))
    for i in (8, 7):
        db.execute("insert into seconds(t, blind, armed, links) values (?, '[]', 0, '{}')", (T0 - i * 1000,))
    db.commit()
    db.close()
    s = Store(path)
    assert s.chain_info() == {"head": {"seq": 0, "hash": ZERO}, "records": 0, "since_t": None, "first_seq": None,
                              "anchor": None, "unsealed": 3}
    s.add(state(T0))
    s.add(event(T0 + 10, "exit", id="new1"))
    assert [r["seq"] for r in s.seconds()] == [None, None, 1] and [e["seq"] for e in s.events()] == [None, 2]
    info = s.chain_info()
    assert (info["records"], info["since_t"], info["first_seq"], info["unsealed"]) == (2, T0, 1, 3)   # and says so
    assert s.records()[0]["prev"] == ZERO and s.verify()["ok"]
    assert [e["kind"] for e in s.events()] == ["enter", "exit"]          # the old rows still answer


def test_an_older_file_opened_by_two_programs_at_once_starts_both(tmp_path):
    # The store and the web server open the same file as the board starts. The one that comes second
    # may find the seq column added between its look and its own try: that must not end it.
    path = tmp_path / "store.db"
    db = sqlite3.connect(path)
    db.executescript(OLD_SCHEMA)
    db.commit()
    db.close()
    s = Store(path)
    for table in ("events", "seconds"):
        s._add_column(table, "seq", "integer")                           # already there: nothing happens
    with pytest.raises(sqlite3.OperationalError):
        s._add_column("no_such_table", "seq", "integer")                 # any other fault is still said
    s.add(state(T0))
    assert s.verify()["ok"] and s.chain_info()["records"] == 1


def test_a_clock_stepped_backwards_does_not_break_the_chain():
    s = filled(Store(":memory:"), 3)
    for i in range(3):
        s.add(state(T0 - 600_000 + i * 1000))            # the board's clock was set ten minutes back
    s.add(state(T0 + 1000))                              # a second saved before: its row is replaced, the link stays
    records = s.records()
    assert [r["seq"] for r in records] == [1, 2, 3, 4, 5, 6, 7]
    assert [r["t"] for r in records][2:5] == [T0 + 2000, T0 - 600_000, T0 - 599_000]
    assert s.verify()["ok"] and s.verify()["checked"] == 7
    assert [r["seq"] for r in s.records(kinds=["second"], since_ms=T0 + 1000, until_ms=T0 + 1000)] == [2, 7]
    since = s.verify_since(T0)                           # by time: from the first record at or after it
    assert since["ok"] and (since["from"], since["to"]) == (1, 7)


def test_pruning_drops_the_oldest_links_only_and_keeps_an_anchor():
    s = filled(Store(":memory:", keep_h=1), 5)
    old = s.records()
    filled(s, 3, T0 + 2 * 3_600_000)
    with s.db:
        s.prune(T0 + 2 * 3_600_000 + 5000)
    info = s.chain_info()
    assert info["anchor"] == {"seq": 5, "hash": old[-1]["hash"]} and info["first_seq"] == 6 and info["records"] == 3
    assert s.records()[0]["prev"] == old[-1]["hash"]
    assert checked(s.verify()) == {"ok": True, "checked": 3, "first_bad_seq": None, "from": 6, "to": 8}
    assert s.verify(1, 8)["from"] == 6                   # a range that starts in what was pruned starts at what is kept
    s.add(state(T0 + 2 * 3_600_000 + 9000))
    assert s.head()["seq"] == 9 and s.verify()["ok"]


def test_a_prune_that_finds_everything_old_keeps_the_head():
    s = filled(Store(":memory:", keep_h=1), 4)
    with s.db:
        s.prune(T0 + 10 * 3_600_000)                     # the clock jumped far ahead
    assert s.chain_info()["records"] == 1 and s.head()["seq"] == 4 and s.chain_info()["anchor"]["seq"] == 3
    s.add(state(T0 + 10 * 3_600_000))
    assert s.head()["seq"] == 5 and s.verify()["ok"] and s.verify()["checked"] == 2


def test_an_edited_record_is_named():
    s = filled(Store(":memory:"), 20)
    body = json.loads(s.db.execute("select body from chain where seq = 12").fetchone()[0])
    with s.db:
        s.db.execute("update chain set body = ? where seq = 12", (canon({**body, "present": 0}),))
    assert checked(s.verify()) == {"ok": False, "checked": 12, "first_bad_seq": 12, "from": 1, "to": 20}
    assert s.verify(13, 20)["ok"] and s.verify(1, 11)["ok"]              # the rest still holds
    assert s.verify(12, 12)["first_bad_seq"] == 12


def test_an_edit_with_its_hash_redone_is_named_at_the_next_record():
    s = filled(Store(":memory:"), 10)
    seq, t, kind, body, prev, _ = s.db.execute("select seq, t, kind, body, prev, hash from chain where seq = 4").fetchone()
    body = canon({**json.loads(body), "present": 0})
    with s.db:
        s.db.execute("update chain set body = ?, hash = ? where seq = 4", (body, record_hash(seq, t, kind, body, prev)))
    assert s.verify()["first_bad_seq"] == 5 and s.verify(5, 10)["first_bad_seq"] == 5


@pytest.mark.parametrize("gone, named", [(6, 6), (1, 1)])
def test_a_removed_record_is_named(gone, named):
    s = filled(Store(":memory:"), 10)
    with s.db:
        s.db.execute("delete from chain where seq = ?", (gone,))
    result = s.verify(1, 10)
    assert not result["ok"] and result["first_bad_seq"] == named


def test_the_prove_it_check_names_the_altered_record_and_never_writes(tmp_path):
    path = tmp_path / "store.db"
    s = filled(Store(path), 30)
    before, size = dump(s), path.read_bytes()
    proof = s.prove()
    assert proof == {"ok": False, "altered_seq": 16, "first_bad_seq": 16, "ms": proof["ms"], "checked": 30,
                     "kind": "second", "t": T0 + 15000}
    assert check.errors(proof, "chain_prove") == []
    named = s.prove(n=10, seq=27)
    assert (named["altered_seq"], named["first_bad_seq"], named["checked"]) == (27, 27, 10)
    assert dump(s) == before and path.read_bytes() == size and s.verify()["ok"]      # the real log is untouched
    assert not s.db.in_transaction
    with pytest.raises(ValueError, match="not among the last 10"):
        s.prove(n=10, seq=3)
    with pytest.raises(ValueError, match="no sealed record"):
        Store(":memory:").prove()


def test_two_processes_add_links_to_one_chain(tmp_path):
    """The store saves the seconds while the web server adds the witnesses' signatures."""
    path = tmp_path / "store.db"
    keeper, web = Store(path), Store(path)
    for i in range(20):
        keeper.add(state(T0 + i * 1000))
        added = web.append("witness_silent", {"node": "pi5"}, T0 + i * 1000 + 500)
        assert added["seq"] == 2 * i + 2 and added["kind"] == "witness_silent" and added["body"] == {"node": "pi5"}
    assert checked(keeper.verify()) == {"ok": True, "checked": 40, "first_bad_seq": None, "from": 1, "to": 40}
    assert [r["seq"] for r in web.records(kinds=["witness_silent"], limit=3, newest=True)] == [36, 38, 40]
    assert [r["seq"] for r in web.records(kinds=["witness_silent"], limit=2)] == [2, 4]


def test_the_verify_answer_fits_the_contract_and_an_empty_chain_checks_nothing():
    empty = Store(":memory:").verify()
    assert empty == {"ok": True, "checked": 0, "first_bad_seq": None, "ms": empty["ms"], "from": None, "to": None}
    assert check.errors(empty, "chain_verify") == []
    s = filled(Store(":memory:"), 5)
    assert check.errors(s.verify(), "chain_verify") == [] and check.errors(s.verify(2, 4), "chain_verify") == []
    assert s.verify(2, 4)["checked"] == 3 and s.verify(4, 99)["to"] == 5


def test_verify_rows_without_a_known_start_still_checks_every_link():
    s = filled(Store(":memory:"), 6)
    rows = dump(s)[2:]
    assert verify_rows(rows) == (True, 4, None)
    assert verify_rows(rows, "ff" * 32) == (False, 1, 3)


def test_an_hour_of_records_is_checked_well_inside_a_second(tmp_path):
    """3,600 records: the size of the check the board runs. The bound is loose on purpose (a slow
    test machine); the measured time is printed with -s."""
    s = Store(tmp_path / "store.db")
    with s.lock, s.db:
        s._begin()
        for i in range(3600):
            body = {k: v for k, v in state(T0 + i * 1000).items() if k in ("links", "pred", "health", "alert", "model")}
            s._seal(T0 + i * 1000, "second", body)
    best = min((s.verify(1, 3600) for _ in range(5)), key=lambda r: r["ms"])
    assert best["ok"] and best["checked"] == 3600
    start = time.perf_counter()
    s.verify()
    whole_call_ms = (time.perf_counter() - start) * 1000
    print(f"\nverify of 3600 records: {best['ms']} ms for the check, {whole_call_ms:.1f} ms with the read from the file")
    assert whole_call_ms < 1000
