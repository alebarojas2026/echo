import re

import pytest

from agent import ask as A
from agent.tools import TOOLS
from store import Store
from store.__main__ import fill_from_sim

NOW = 1_763_149_500_000
ZONES = {1: "Bed", 2: "Chair", 3: "Hall", 4: "Bathroom"}
LINKS = ["pi5>unoq:wifi", "east>pi5:ble"]
NUMBER = re.compile(r"\d+(?:\.\d+)?")


@pytest.fixture(scope="module")
def store():
    s = Store(":memory:")
    fill_from_sim(s, "demo", end_ms=NOW)
    for i, (kind, info) in enumerate((("armed", {}), ("intrusion", {"zone": 4}))):
        s.add({"type": "event", "t": NOW - 500 + i, "kind": kind, "id": f"x{i}", "src": "sim", "info": info})
    return s


def model(tool, minutes=10, zone=0, link="any"):
    """A fake model that always picks this."""
    return lambda messages, schema: {"tool": tool, "minutes": minutes, "zone": zone, "link": link}


def run(store, tool, **kw):
    return A.ask("a question", store, model(tool, **kw), now_ms=NOW, zones=ZONES, links=LINKS)


def numbers_in(value) -> set:
    if isinstance(value, dict):
        return set().union(*map(numbers_in, value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*map(numbers_in, value)) if value else set()
    return set(NUMBER.findall(str(value)))


EXPECT = {"presence": "Yes. Someone was here for", "still_spans": "The longest time without movement was",
          "alerts": "No-movement alerts in the last 10 minutes: 1.", "intrusions": "Intrusion alerts in the last 10 minutes: 1.",
          "link_history": "In the last 10 minutes: east>pi5:ble read", "explain_advice": "The last advice was: ",
          "model_card": "Model sim runs on this board"}


@pytest.mark.parametrize("tool", list(TOOLS))
def test_each_tool_answers_from_its_rows(store, tool):
    reply = run(store, tool)
    assert EXPECT[tool] in reply["answer"], reply["answer"]
    assert reply["tool"] == tool and reply["picked_by"] == "llm" and reply["src"] == "sim" and reply["rows"]
    # no number that isn't in a row (or the minutes that were asked for)
    assert numbers_in(reply["answer"]) <= numbers_in(reply["rows"]) | {str(reply["args"]["minutes"])}


def test_a_zone_and_a_link_narrow_the_answer(store):
    assert "Nobody was seen in Bed" in run(store, "presence", zone=1)["answer"]
    assert {r.get("zone", 4) for r in run(store, "presence", zone=4)["rows"]} == {4}
    assert [r["link"] for r in run(store, "link_history", link="pi5>unoq:wifi")["rows"]] == ["pi5>unoq:wifi"]


def test_no_prediction_is_never_reported_as_nobody(store):
    assert "there was no prediction, so I can't say" in run(store, "presence", zone=1)["answer"]


def test_an_empty_store_says_it_has_no_records():
    empty = Store(":memory:")
    for tool in TOOLS:
        reply = run(empty, tool)
        assert reply["rows"] == [] and not NUMBER.search(reply["answer"].replace("10 minutes", ""))
    assert run(empty, "presence")["answer"] == "I have no records for the last 10 minutes."


@pytest.mark.parametrize("pick", [{"tool": "none"}, {"tool": "delete_everything"}, "presence", None, {}])
def test_a_question_that_fits_no_tool_gets_the_list(store, pick):
    reply = A.ask("what is the weather?", store, lambda m, s: pick, now_ms=NOW, zones=ZONES, links=LINKS)
    assert reply["tool"] is None and reply["rows"] == [] and reply["answer"].startswith("I can answer: ")


def test_arguments_outside_the_lists_never_reach_a_tool():
    tool, args = A.checked({"tool": "presence", "minutes": 10**9, "zone": 9, "link": "x; drop table"}, ZONES, LINKS)
    assert (tool, args) == ("presence", {"minutes": 1440, "zone": None, "link": None})
    assert A.checked({"tool": "presence", "minutes": "ten", "zone": 0, "link": "any"}, ZONES, LINKS)[1]["minutes"] == 10


def test_the_schema_holds_the_model_to_the_tools_and_the_layout():
    props = A.schema(ZONES, LINKS)["properties"]
    assert props["tool"]["enum"] == list(TOOLS) + ["none"]
    assert props["zone"]["enum"] == [0, 1, 2, 3, 4] and props["link"]["enum"] == ["any"] + LINKS
    system = A.messages("q", ZONES, LINKS)[0]["content"]
    assert all(name in system for name in TOOLS) and "4 for Bathroom" in system


def test_when_the_model_fails_keywords_pick_and_the_reply_says_so(store):
    def down(messages, schema):
        raise OSError("connection refused")
    reply = A.ask("Any alerts in the last 2 hours?", store, down, now_ms=NOW, zones=ZONES, links=LINKS)
    assert (reply["tool"], reply["picked_by"], reply["args"]["minutes"]) == ("alerts", "rules", 120)


@pytest.mark.parametrize("question, tool", [
    ("was anyone here in the last 10 minutes?", "presence"), ("how long did someone stay still?", "still_spans"),
    ("did the intrusion alert go off?", "intrusions"), ("how is the signal on the links?", "link_history"),
    ("why move the router?", "explain_advice"), ("what model runs here?", "model_card"), ("what's the weather?", "none")])
def test_keyword_picks(question, tool):
    assert A.by_rules(question)["tool"] == tool


def test_the_time_per_answer_is_returned(store):
    ticks = iter([10.0, 10.25])
    reply = A.ask("q", store, model("alerts"), now_ms=NOW, zones=ZONES, links=LINKS, timer=lambda: next(ticks))
    assert reply["ms"] == 250


def test_the_layout_comes_from_nodes_json():
    zones, links = A.layout()
    assert zones and links and all(isinstance(z, int) for z in zones)


def test_the_command_line_answers_from_a_store_filled_by_the_sim(tmp_path, capsys):
    from store.__main__ import main as fill
    db = str(tmp_path / "store.db")
    fill(["--sim", "demo", "--db", db])
    A.main(["--db", db, "--no-llm", "was anyone here in the last 10 minutes?"])
    out = capsys.readouterr().out
    assert "Yes. Someone was here for" in out and "tool presence" in out and "picked by rules, records sim" in out
