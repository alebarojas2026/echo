"""The store's history, the incident report and the span on Ask answers (CONTRACTS.md section 10)."""
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from agent import ask as A
from agent import report as R
from board import serve
from store import Store
from store.__main__ import fill_from_sim

T0 = 1_763_149_500_000
ZONES = {1: "Left", 2: "Right"}
SCHEMAS = Path(__file__).resolve().parents[2] / "contracts" / "schemas"


def second(store, s, present=True, zone=2, health="ok", armed=False, tamper=(), alert="none", motion="still"):
    pred = None if present is None else (
        {"present": True, "kind": "person", "zone": zone, "zone_set": [zone], "motion": motion, "still_s": 1.0}
        if present else {"present": False, "kind": "none", "zone": 0, "zone_set": [], "motion": None})
    store.add({"type": "state", "t": T0 + s * 1000, "src": "sim", "pred": pred, "links": [], "armed": armed,
               "health": {"status": health, "blind": []}, "alert": {"state": alert}, "tamper": list(tamper)})


def event(store, s, kind, **info):
    store.add({"type": "event", "t": T0 + s * 1000, "kind": kind, "id": f"{kind}{s}", "src": "sim", "info": info})


def armed_store(intrusions=(), tamper=(), disarm=60):
    """Armed at 10 s; someone is there from 20 to 39 s; blind (unknown) from 40 to 45 s; no row for 50-52 s."""
    s = Store(":memory:")
    for i in range(0, 70):
        if 50 <= i <= 52:
            continue
        if 40 <= i <= 45:
            second(s, i, present=None, health="blind", armed=True, tamper=["east"] if tamper else ())
        else:
            second(s, i, present=20 <= i < 40, armed=10 <= i < (disarm or 999))
    event(s, 10, "armed")
    for at, where in intrusions:
        event(s, at, "intrusion", **where)
    for at, node in tamper:
        event(s, at, "tamper", node=node)
    if disarm:
        event(s, disarm, "disarmed")
    return s


# ---- GET /history

def test_history_has_the_visit_keeps_the_gap_and_never_turns_unknown_into_empty():
    h = armed_store().history(T0 + 18_000, T0 + 54_000)
    by_t = {(r["t"] - T0) // 1000: r for r in h["rows"]}
    assert (h["from_t"], h["to_t"], h["step_s"]) == (T0 + 18_000, T0 + 54_000, 1)
    assert sorted(by_t) == [*range(18, 50), 53, 54]                      # 50-52 were never saved: still missing
    assert by_t[19] == {"t": T0 + 19_000, "present": False, "zone": 0, "zone_set": [], "motion": None, "armed": True,
                        "alert": False, "health": "ok", "tamper": []}
    assert (by_t[25]["present"], by_t[25]["zone"], by_t[25]["zone_set"], by_t[25]["motion"]) == (True, 2, [2], "still")
    assert by_t[42] == {"t": T0 + 42_000, "present": None, "zone": None, "zone_set": [], "motion": None, "armed": True,
                        "alert": False, "health": "blind", "tamper": []}


def test_history_carries_tamper_and_the_alert():
    s = armed_store(tamper=[(41, "east")])
    second(s, 80, alert="check_on")
    assert s.history(T0 + 41_000, T0 + 41_000)["rows"][0]["tamper"] == ["east"]
    assert s.history(T0 + 80_000, T0 + 80_000)["rows"][0]["alert"] is True


def test_history_refuses_more_than_30_minutes_and_a_backwards_stretch():
    s = armed_store()
    assert s.history(T0, T0 + 30 * 60_000)["rows"]
    with pytest.raises(ValueError, match="at most 30 minutes"):
        s.history(T0, T0 + 30 * 60_000 + 1)
    with pytest.raises(ValueError, match="before"):
        s.history(T0 + 5, T0)


def test_an_older_store_file_gets_the_new_columns(tmp_path):
    import sqlite3
    db = sqlite3.connect(tmp_path / "old.db")
    db.execute("create table seconds(t integer primary key, src text, present integer, kind text, zone integer, "
               "motion text, still_s real, health text, blind text not null, alert text, alert_zone integer, "
               "armed integer not null, cam text, router text, links text not null, advice text, model text)")
    db.execute("insert into seconds(t, present, zone, health, blind, armed, links) values (?, 1, 2, 'ok', '[]', 0, '{}')", (T0,))
    db.commit(), db.close()
    s = Store(tmp_path / "old.db")
    second(s, 1, tamper=["east"])
    rows = s.history(T0, T0 + 1000)["rows"]
    assert (rows[0]["zone_set"], rows[0]["tamper"], rows[1]["tamper"]) == ([], [], ["east"])


# ---- GET /report

def run(store, llm=None, **kw):
    said = []
    out = R.report(store, llm, now_ms=T0 + 70_000, zones=ZONES, said=said.append, **kw)
    return out, said[0] if said else None


def test_report_with_no_intrusion():
    out, why = run(armed_store())
    assert (out["armed_from_t"], out["armed_to_t"]) == (T0 + 10_000, T0 + 60_000)
    assert (out["intrusions"], out["tamper"], out["present_s"], out["blind_s"], out["passed_by"]) == ([], [], 20, 6, None)
    assert out["rows"] == 48 and why == "template" and isinstance(out["ms"], int)   # 10..60 s, less the 3 never saved
    assert "No intrusion alert." in out["text"] and "Someone was here for 20 s." in out["text"]
    assert "The sensor was blind for 6 s." in out["text"] and R.problem(out["text"], out) is None


def test_report_with_one_intrusion_still_armed():
    out, _ = run(armed_store(intrusions=[(20, {"zone": 2})], disarm=None))
    assert out["armed_to_t"] is None and out["intrusions"] == [{"t": T0 + 20_000, "zone": 2}]
    assert "and still armed." in out["text"] and "Intrusion alerts: 1, the first on the right at " in out["text"]


def test_report_with_several_intrusions_a_hall_link_and_a_tamper():
    out, _ = run(armed_store(intrusions=[(20, {"zone": 1}), (30, {"link": "h>unoq:ble"}), (35, {"zone": 2})],
                             tamper=[(41, "east")]))
    assert out["intrusions"] == [{"t": T0 + 20_000, "zone": 1}, {"t": T0 + 30_000, "link": "h>unoq:ble"},
                                 {"t": T0 + 35_000, "zone": 2}]
    assert out["tamper"] == [{"t": T0 + 41_000, "node": "east"}]
    assert "Intrusion alerts: 3, the first on the left" in out["text"] and "Tamper alerts: 1; " in out["text"]
    named = R.device_names().get("east")          # the layout's own name for it, when nodes.json has one
    assert f"{'the ' + named if named else 'the device east'} went quiet first, at " in out["text"]
    assert R.problem(out["text"], out) is None
    assert "the East beacon went quiet first, at " in R.template(out, ZONES, {"east": "East beacon"})
    assert "the first in the Hall zone at " in R.template(out, {1: "Hall"})


def test_only_the_last_armed_stretch_counts_and_events_outside_it_do_not():
    s = armed_store(intrusions=[(5, {"zone": 1}), (20, {"zone": 2}), (65, {"zone": 1})])
    assert [h["t"] for h in run(s)[0]["intrusions"]] == [T0 + 20_000]
    event(s, 66, "armed")
    assert run(s)[0]["armed_from_t"] == T0 + 66_000 and run(s)[0]["armed_to_t"] is None
    assert run(s, from_t=T0, to_t=T0 + 30_000)[0]["present_s"] == 11          # an asked-for stretch: 20..30 s


def test_never_armed_gives_no_report():
    s = Store(":memory:")
    second(s, 1)
    assert R.report(s, now_ms=T0 + 5000, zones=ZONES) is None


def test_the_models_text_is_used_only_when_every_number_is_the_reports_own():
    s = armed_store(intrusions=[(20, {"zone": 2})])
    good = "While armed, one intrusion alert came from the right. Someone stayed for 20 s and the sensor was blind for 6 s."
    written, why = run(s, lambda m: good)
    fields = lambda r: {k: v for k, v in r.items() if k not in ("text", "ms")}   # noqa: E731
    assert (written["text"], why) == (good, "llm") and fields(written) == fields(run(s)[0])
    for bad, reason in (("Someone was here for 25 s.", "a number that is not in the report (25)"),
                        ("There were three intrusion alerts.", "a number that is not in the report (three)"),
                        ("A burglar was here for 20 s.", "a word we never use (burglar)"),
                        ("She was here for 20 s.", "a word we never use (She)"),
                        ("Armed at 99:99:99. Someone was here for 20 s.", "a number that is not in the report (99)"),
                        ("", "empty"), ("word " * 61, "more than 60 words")):
        out, why = run(s, lambda m, bad=bad: bad)
        assert why == f"template ({reason})" and out["text"] == run(s)[0]["text"], (bad, why)


def test_a_slow_or_failing_model_gives_the_template():
    s, gate = armed_store(), threading.Event()

    def slow(messages):
        gate.wait(5)
        return "Someone was here for 20 s."
    out, why = run(s, slow, timeout_s=0.05)
    gate.set()
    assert why.startswith("template (no reply in") and out["text"].startswith("Armed from ")

    def down(messages):
        raise OSError("connection refused")
    assert run(s, down)[1] == "template (connection refused)"


def test_the_model_is_given_only_the_facts():
    seen = []
    run(armed_store(intrusions=[(20, {"zone": 2})]), lambda m: seen.append(m) or "")
    assert seen[0][1]["content"].startswith("Facts: Armed from ") and "Say intrusion alert" in seen[0][0]["content"]


def test_the_command_prints_the_last_report(tmp_path, capsys):
    db = tmp_path / "store.db"
    s = Store(db)
    fill_from_sim(s, "arrival")
    last = s.latest()["t"]
    s.add({"type": "event", "t": last - 20_000, "kind": "armed", "id": "a", "src": "sim", "info": {}})
    s.add({"type": "event", "t": last - 15_000, "kind": "intrusion", "id": "i", "src": "sim", "info": {"zone": 1}})
    assert R.main(["--db", str(db), "--no-llm"]) == 0
    out = capsys.readouterr().out
    assert "and still armed. Intrusion alerts: 1" in out and '"present_s": ' in out and "text from: template" in out
    assert R.main(["--db", str(tmp_path / "empty.db"), "--no-llm"]) == 1


# ---- span on Ask answers

def test_answers_about_a_stretch_of_time_carry_a_span_inside_the_record():
    s = Store(":memory:")
    fill_from_sim(s, "demo", end_ms=T0)
    zones, links = {1: "Bed", 2: "Chair", 3: "Hall", 4: "Bathroom"}, ["pi5>unoq:wifi"]
    pick = lambda tool: (lambda m, sc: {"tool": tool, "minutes": 10, "zone": 0, "link": "any"})   # noqa: E731
    spans = {t: A.ask("q", s, pick(t), now_ms=T0, zones=zones, links=links).get("span")
             for t in ("presence", "still_spans", "alerts", "intrusions", "link_history", "explain_advice", "model_card")}
    assert [t for t, sp in spans.items() if sp] == ["presence", "still_spans", "alerts"]
    for sp in filter(None, spans.values()):
        assert sp["from_t"] < sp["to_t"] <= T0 and sp["to_t"] - sp["from_t"] <= 30 * 60_000
        assert s.history(sp["from_t"], sp["to_t"])["rows"]               # the replay has something to play
    assert "span" not in A.ask("q", Store(":memory:"), pick("presence"), now_ms=T0, zones=zones, links=links)


# ---- the board's web server (handlers mounted by board/serve.py's routes)

MOUNT = pytest.mark.skipif(not hasattr(serve, "ApiError"), reason="board/serve.py can't mount routes yet (#566)")


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def start(tmp_path, store):
    from agent import endpoints
    routes = {("GET", "/history"): endpoints.history(store),
              ("GET", "/report"): endpoints.report(store, None, now_ms=T0 + 70_000, zones=ZONES)}
    server = serve.make_server("127.0.0.1", 0, dist=tmp_path, nodes=tmp_path / "n.json", proof=tmp_path / "p.json",
                               routes=routes)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


@pytest.fixture
def board(tmp_path):
    server, url = start(tmp_path, armed_store(intrusions=[(20, {"zone": 2})], tamper=[(41, "east")]))
    yield url
    server.shutdown()


@MOUNT
def test_get_history_and_report_from_the_board(board):
    status, h = get(f"{board}/history?from_t={T0 + 18_000}&to_t={T0 + 54_000}")
    assert status == 200 and len(h["rows"]) == 34 and h["step_s"] == 1
    assert {type(r["present"]) for r in h["rows"]} == {bool, type(None)}          # the contract's row, not 0/1
    assert all(type(r["armed"]) is bool and type(r["alert"]) is bool and isinstance(r["tamper"], list) for r in h["rows"])
    status, r = get(f"{board}/report")
    assert status == 200 and r["intrusions"] == [{"t": T0 + 20_000, "zone": 2}] and r["text"].startswith("Armed from ")
    assert get(f"{board}/report?from_t={T0}&to_t={T0 + 30_000}")[1]["armed_from_t"] == T0


@MOUNT
@pytest.mark.parametrize("query, says", [
    ("/history", "both"), ("/history?from_t=5", "both"), ("/history?from_t=a&to_t=b", "epoch milliseconds"),
    (f"/history?from_t={T0}&to_t={T0 + 31 * 60_000}", "at most 30 minutes"), ("/history?from_t=9&to_t=1", "before"),
    ("/report?from_t=5", "both"), ("/report?from_t=9&to_t=1", "before")])
def test_a_bad_stretch_is_400_with_a_plain_message(board, query, says):
    status, reply = get(board + query)
    assert status == 400 and says in reply["error"]


@MOUNT
def test_never_armed_is_404(tmp_path):
    server, url = start(tmp_path, Store(":memory:"))
    status, reply = get(url + "/report")
    assert status == 404 and "has not been armed" in reply["error"]
    server.shutdown()


def test_the_routes_are_the_two_get_endpoints(tmp_path):
    from agent import endpoints
    assert sorted(endpoints.routes(tmp_path / "store.db", "http://127.0.0.1:9")) == [("GET", "/history"), ("GET", "/report")]
