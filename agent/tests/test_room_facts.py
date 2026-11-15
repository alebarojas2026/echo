import json
from pathlib import Path

import pytest

from agent.ask import ask
from contracts.check import errors
from store import Store
from store.__main__ import fill_from_sim

NOW = 1_763_149_500_000


@pytest.fixture
def recorded():
    store = Store(":memory:")
    fill_from_sim(store, "router_move", end_ms=NOW)
    yield store
    store.close()


def query(store, question, **kw):
    reply = ask(question, store, now_ms=NOW, **kw)
    assert errors(reply, "ask_reply") == []
    assert reply["picked_by"] == "rules"
    return reply


def test_weakest_uses_latest_wifi_drop_and_configured_names(recorded, tmp_path):
    layout = tmp_path / "nodes.json"
    layout.write_text(json.dumps({"zones": [{"id": 1, "name": "At the desk"}],
                                  "nodes": [{"id": "pi5", "name": "Desk radio"}, {"id": "unoq", "name": "Board"}],
                                  "links": [{"id": "pi5>unoq:wifi", "tx": "pi5", "rx": "unoq"}]}))
    # Compare actual simulated saved drops, rather than inventing a baseline.
    latest = recorded.latest()
    reply = query(recorded, "Where is the Wi-Fi weakest right now?", nodes_path=layout)
    row = reply["rows"][0]
    expected = max((v["drop_db"] for k, v in latest["links"].items() if k.endswith(":wifi") and v["status"] == "ok"))
    assert row["drop_db"] == expected
    assert row["name"] == "Desk radio to Board"
    assert reply["tool"] == "link_history"


def test_blocked_wifi_reports_saved_advice_and_drop(recorded):
    reply = query(recorded, "Did anything block the Wi-Fi in the last 10 minutes?")
    assert reply["tool"] == "explain_advice"
    assert "blockage advice" in reply["answer"]
    row = reply["rows"][0]
    assert row["max_drop_db"] == max(r["links"][row["link"]]["drop_db"] for r in recorded.seconds()
                                      if row["link"] in r["links"] and r["links"][row["link"]]["drop_db"] is not None)


def test_router_move_reports_measured_before_after_and_gain(recorded):
    reply = query(recorded, "What did moving the router do?")
    row = reply["rows"][0]
    assert row["before_dbm"] is not None and row["after_dbm"] is not None
    assert row["gain_db"] == round(row["after_dbm"] - row["before_dbm"], 2)
    assert "gain of" in reply["answer"]


def test_no_dead_zone_and_no_move_in_simulated_empty_room():
    store = Store(":memory:")
    fill_from_sim(store, "empty_room", end_ms=NOW)
    assert "No dead zone was found" in query(store, "Did anything block the Wi-Fi?")["answer"]
    assert "router has not been moved" in query(store, "What did moving the router do?")["answer"]


@pytest.mark.parametrize("question", ["Are you recording me?", "Is anything leaving this room?"])
def test_privacy_explains_local_records_without_inventing_counts(recorded, question):
    reply = query(recorded, question, privacy_reader=lambda **kw: {"ok": False, "why": "meter stopped"})
    assert reply["tool"] == "model_card"
    assert "once a second" in reply["answer"] and "SQLite" in reply["answer"]
    assert "no camera images or identities" in reply["answer"]
    assert "unavailable" in reply["answer"] and "0 images" not in reply["answer"]


def test_privacy_uses_live_meter_even_when_counts_are_nonzero(recorded):
    meter = {"ok": True, "images": 2, "bytes_out": 51, "since_t": NOW - 60_000, "t": NOW}
    reply = query(recorded, "Are you recording me?", privacy_reader=lambda **kw: meter)
    assert "2 images stored and 51 internet bytes out" in reply["answer"]
    assert reply["rows"][0]["meter"] == meter


@pytest.mark.parametrize("t", [NOW - 60_000, NOW + 3000])
def test_privacy_rejects_stale_or_future_meter(recorded, t):
    meter = {"ok": True, "images": 0, "bytes_out": 0, "since_t": NOW - 60_000, "t": t}
    assert "unavailable" in query(recorded, "Are you recording me?", privacy_reader=lambda **kw: meter)["answer"]


def test_weakest_does_not_describe_old_reading_as_current(recorded):
    reply = ask("Where is Wi-Fi weakest right now?", recorded, now_ms=NOW + 60_000)
    assert "no current Wi-Fi" in reply["answer"]


def test_movement_question_is_not_mistaken_for_router_move(recorded):
    assert query(recorded, "How long did someone stay without moving?")["tool"] == "still_spans"


def test_missing_baseline_does_not_name_a_weakest_link():
    store = Store(":memory:")
    store.add({"type": "state", "t": NOW, "src": "sim", "links": [
        {"id": "pi5>unoq:wifi", "dbm": -60, "drop_db": None, "status": "ok"},
        {"id": "pi5>unoq:ble", "dbm": -80, "drop_db": 20, "status": "ok"}]})
    assert "no current Wi-Fi baseline" in query(store, "Where is the Wi-Fi weakest?")["answer"]


def test_move_without_measurement_says_result_is_pending():
    store = Store(":memory:")
    store.add({"type": "event", "t": NOW, "id": "move", "kind": "router_moved", "src": "sim", "info": {}})
    assert "no measured before-and-after" in query(store, "What did moving the router do?")["answer"]


@pytest.mark.parametrize("kind, link, expected", [
    ("person", "pi5>pi5b:wifi", False), ("object", "pi5>unoq:wifi", False), ("object", "pi5>pi5b:wifi", True)])
def test_gate_advice_needs_an_object_and_the_crossing_wifi(kind, link, expected):
    gate = Path(__file__).resolve().parents[2] / "narrator/tests/gate_nodes.json"
    s = Store(":memory:")
    s.add({"type": "state", "t": NOW, "src": "sim", "pred": {"kind": kind, "present": kind == "person"},
           "links": [{"id": link, "status": "ok", "drop_db": 12}],
           "advice": {"id": "a1", "link": link, "text": "Move the router 30 cm.", "before_dbm": -60, "after_dbm": None}})
    out = query(s, "Did anything block the Wi-Fi?", nodes_path=gate)
    assert ("Something was left in the Wi-Fi line" in out["answer"]) is expected
    assert "30 cm" not in out["answer"]
    if expected:
        assert "Clear the obstruction or move Pi B" in out["answer"]
