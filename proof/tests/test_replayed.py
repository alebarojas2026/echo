"""Recordings replayed through the real brain on the one-spot layout, with no model anywhere."""
import json

import pytest

pytest.importorskip("brain.core")

from proof import render_table, replayed as R
from proof.provenance import empty_proof
from proof.tests.conftest import FIXTURES

LINE = "pi5>pi5b:wifi"
GATE = FIXTURES.parents[2] / "radio" / "layouts" / "gate.json"   # the layout file the kit runs: it names the presence line
LEVELS = {"baseline": -40, "empty": -40, "person": -58, "still": -58, "walk": -58}


def write(folder, name, kind, start, seconds=10, src="live", level=None):
    """One short recording as the bus writes it: 25 readings a second on the Wi-Fi line."""
    rows = [dict(v=2, type="meta", recv_t=start, src=src, session=name, purpose="demo")]
    for i in range(seconds * 25):
        dbm = LEVELS[kind] if level is None else level
        if kind == "moving":
            dbm = -58 + (6 if (i // 12) % 2 else 0)
        rows.append(dict(v=2, type="rssi", src=src, recv_t=start + i * 40, link=LINE, dbm=dbm + (i % 2) * 0.5))
    (folder / f"{name}.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")


def sitting(folder, kinds, first=1_000_000, **extra):
    """A run of recordings 19 s apart (the seconds between them are not recorded), and its plan."""
    sessions = []
    for i, (kind, role) in enumerate(kinds):
        name = f"{extra.get('id', 'main')}-{i}"
        if kind == "moving":
            LEVELS.setdefault("moving", -58)
        write(folder, name, kind, first + i * 19000, level=extra.get("level") if kind == "person" else None)
        sessions.append({"session": name, "is": kind, "role": role})
    return {"id": extra.get("id", "main"), "placement": extra.get("placement", "in the open"),
            **({"limit": extra["limit"]} if "limit" in extra else {}), "sessions": sessions}


def plan(*runs, **more):
    return {"truth": "operator", "people": 1, "night": "one night", "recorded_commit": "a" * 40, "runs": list(runs), **more}


@pytest.fixture(autouse=True)
def build(monkeypatch):
    monkeypatch.setattr(R, "brain_build", lambda root: "b" * 40)


def test_stands_empty_time_and_the_delay_come_from_the_brains_own_decisions(tmp_path):
    run = sitting(tmp_path, [("baseline", "tuning"), ("person", "report"), ("empty", "report"),
                             ("person", "report"), ("empty", "report"), ("still", "report")])
    result = R.report(tmp_path, plan(run), GATE)
    total = result["total"]
    assert total["stands"] == {"n": 3, "found": 3} and total["dropouts"] == 0
    assert all(0.3 <= s <= 1.5 for s in total["decide_s"]) and len(total["decide_s"]) == 3
    assert total["empty"]["false_presences"] == 0 and total["empty"]["sessions"] == 2
    assert 17 < total["empty"]["seconds"] < 20      # two 10 s recordings less the let-go of the person before
    assert all(0 < s <= 2 for s in total["release_s"])
    assert total["still"]["sessions"] == 1 and total["still"]["n"] > 50 and total["still"]["right"] == total["still"]["n"]
    assert result["brain_commit"] == "b" * 40 and result["presence"]["line"] == LINE
    assert [s["role"] for s in result["sources"]].count("report") == 5 and len(result["sources"][0]["sha256"]) == 64


def test_tuning_sessions_are_played_and_never_scored(tmp_path):
    run = sitting(tmp_path, [("baseline", "tuning"), ("person", "tuning"), ("empty", "tuning"), ("walk", "tuning"),
                             ("empty", "tuning"), ("person", "report"), ("empty", "report")])
    result = R.report(tmp_path, plan(run), GATE)
    assert result["total"]["stands"] == {"n": 1, "found": 1} and result["total"]["empty"]["sessions"] == 1
    assert result["tuning_only"] == {"walk": 1}
    assert "Walk-throughs: seen once, used for tuning, not a result." in R.limits(result)
    run["sessions"][-1]["role"] = run["sessions"][-2]["role"] = "tuning"
    with pytest.raises(ValueError, match="nothing to report"):
        R.report(tmp_path, plan(run), GATE)


def test_a_false_presence_on_an_empty_spot_is_counted_however_short(tmp_path):
    run = sitting(tmp_path, [("baseline", "tuning"), ("empty", "report"), ("empty", "report")])
    name = run["sessions"][2]["session"]
    rows = [json.loads(line) for line in (tmp_path / f"{name}.jsonl").read_text().splitlines()]
    for row in rows[100:160]:     # 2.4 s of a person's drop inside an "empty" recording
        row["dbm"] = -58
    (tmp_path / f"{name}.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    empty = R.report(tmp_path, plan(run), GATE)["total"]["empty"]
    assert empty["false_presences"] == 1 and empty["false_present_s"] > 1


def test_a_stated_limit_is_reported_beside_the_total_and_not_inside_it(tmp_path):
    good = sitting(tmp_path, [("baseline", "tuning"), ("person", "report"), ("empty", "report")])
    low = sitting(tmp_path, [("baseline", "report"), ("person", "report"), ("empty", "report")], first=9_000_000,
                  id="low", placement="the far device low", limit="It fails.", level=-44)
    result = R.report(tmp_path, plan(good, low), GATE)
    assert result["total"]["stands"] == {"n": 1, "found": 1}
    assert result["runs"][1]["stands"] == {"n": 1, "found": 0}
    text = "\n".join(R.table(result))
    assert "Stated limit: the far device low | 0 of 1 stands found" in text
    assert "- the far device low: 0 of 1 stands found. It fails." in text
    with pytest.raises(ValueError, match="stated limit"):
        R.report(tmp_path, plan(low), GATE)


@pytest.mark.parametrize("fault", ["sim", "walk", "twice", "truth", "commit", "role", "baseline", "layout"])
def test_anything_that_is_not_measured_input_is_refused(tmp_path, fault):
    run = sitting(tmp_path, [("baseline", "tuning"), ("person", "report"), ("empty", "report")])
    doc, layout = plan(run), GATE
    if fault == "sim":
        write(tmp_path, run["sessions"][1]["session"], "person", 1_019_000, src="sim")
    if fault == "walk":
        run["sessions"][1]["is"] = "walk"
    if fault == "twice":
        run["sessions"].append(dict(run["sessions"][1]))
    if fault == "truth":
        doc["truth"] = "guess"
    if fault == "commit":
        doc["recorded_commit"] = "abc1234"
    if fault == "role":
        del run["sessions"][2]["role"]
    if fault == "baseline":
        run["sessions"][0]["is"] = "empty"
    if fault == "layout":
        layout = FIXTURES / "desk-nodes.json"    # no presence line: nothing could decide without a model
    with pytest.raises(ValueError):
        R.report(tmp_path, doc, layout)


def test_rows_say_what_they_rest_on_and_render_into_the_generated_block(tmp_path):
    run = sitting(tmp_path, [("baseline", "tuning"), ("person", "report"), ("empty", "report")])
    result = R.report(tmp_path, plan(run), GATE)
    rows = R.sentences(result)
    assert rows[0][1] == "1 of 1 stands found; with this few trials the true rate is probably between 2% and 100%"
    assert all(R.WORDS in row[2] for row in rows)
    assert any("The step-on itself was not recorded as an event" in row[2] for row in rows)
    document = render_table.render("# Proof\n", empty_proof(), replayed=result)
    assert "## Replayed from recordings taken on the kit" in document and "b" * 40 in document
    assert document == render_table.render(document, empty_proof(), replayed=result)     # rerunning changes nothing
    assert "Replayed" not in render_table.render(document, empty_proof())
    for key, value in (("method", "by hand"), ("source", "sim"), ("brain_commit", "")):
        with pytest.raises(ValueError):
            R.table(dict(result, **{key: value}))


def test_the_rate_ceiling_and_the_outward_ranges():
    assert round(R.rate_ceiling(0, 9.4), 2) == 0.39      # nothing in 9.4 minutes cannot show less than this
    assert R.rate_ceiling(2, 10) > R.rate_ceiling(0, 10)
    assert R.plain_range(10, 10, "stands found").endswith("between 69% and 100%")
    assert R.plain_range(0, 5, "stands found").endswith("between 0% and 53%")
