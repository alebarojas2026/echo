import json

import pytest

from store import Store, summary
from store.__main__ import fill_from_sim

T0 = 1_763_149_500_000


def state(t, pred="default", **over):
    if pred == "default":
        pred = {"present": True, "kind": "person", "zone": 2, "motion": "still", "still_s": 4.2}
    msg = {"v": 2, "type": "state", "t": t, "seq": 1, "src": "live", "cam": "on", "router": "S-home",
           "links": [{"id": "east>pi5:ble", "dbm": -63.0, "drop_db": 4.9, "status": "ok"}],
           "health": {"status": "ok", "blind": [], "reason": None}, "pred": pred,
           "alert": {"state": "none", "zone": None, "still_s": 0, "limit_s": None}, "advice": None,
           "model": {"trained": True, "ver": "m3"}}
    return {**msg, **over}


def event(t, kind, id="e1", **info):
    return {"v": 2, "type": "event", "t": t, "seq": 2, "src": "live", "id": id, "kind": kind, "info": info}


def test_one_summary_a_second():
    s = Store(":memory:")
    assert [s.add(state(T0 + ms)) for ms in (0, 100, 900, 1000, 1100)] == [True, False, False, True, False]
    assert [r["t"] for r in s.seconds()] == [T0, T0 + 1000]


def test_summary_keeps_what_the_agent_needs():
    s = Store(":memory:")
    s.add(state(T0, armed=True))
    row = s.latest()
    assert (row["present"], row["kind"], row["zone"], row["motion"], row["armed"]) == (1, "person", 2, "still", 1)
    assert row["links"] == {"east>pi5:ble": {"dbm": -63.0, "drop_db": 4.9, "status": "ok"}}
    assert row["model"]["ver"] == "m3" and row["advice"] is None and row["blind"] == []


def test_no_prediction_is_unknown_not_empty():
    assert summary(state(T0, pred=None))["present"] is None
    assert summary(state(T0, pred={"present": False, "kind": "none", "zone": 0, "motion": None}))["present"] == 0


def test_every_event_is_kept_once_in_order():
    s = Store(":memory:")
    assert s.add(event(T0 + 5, "alert_on", "e2", zone=4)) and s.add(event(T0, "enter", "e1", zone=2))
    assert not s.add(event(T0, "enter", "e1", zone=2))          # the same event again
    assert [(e["kind"], e["info"]) for e in s.events()] == [("enter", {"zone": 2}), ("alert_on", {"zone": 4})]
    assert [e["kind"] for e in s.events(kinds=("alert_on",))] == ["alert_on"]
    assert s.events(T0 + 6) == []


@pytest.mark.parametrize("msg", [None, [], {"type": "state"}, {"type": "rssi", "t": T0}, {"type": "event", "t": T0}])
def test_other_messages_are_ignored(msg):
    assert Store(":memory:").add(msg) is False


def test_old_rows_are_dropped():
    s = Store(":memory:", keep_h=1)
    s.add(state(T0)), s.add(event(T0, "enter"))
    s.add(state(T0 + 2 * 3_600_000))
    s.prune(T0 + 2 * 3_600_000)
    assert [r["t"] for r in s.seconds()] == [T0 + 2 * 3_600_000] and s.events() == []


def test_a_file_store_is_read_by_a_second_connection(tmp_path):
    Store(tmp_path / "x" / "store.db").add(state(T0))
    assert Store(tmp_path / "x" / "store.db").latest()["t"] == T0


def test_fill_from_the_simulated_demo_ends_at_the_given_time():
    s = Store(":memory:")
    assert fill_from_sim(s, "demo", end_ms=T0) > 60
    kinds = [e["kind"] for e in s.events()]
    assert kinds.index("enter") < kinds.index("alert_on") < kinds.index("alert_off")
    rows = s.seconds()
    assert rows[-1]["t"] == T0 and {r["src"] for r in rows} == {"sim"}
    json.dumps(rows)   # every column is plain JSON
