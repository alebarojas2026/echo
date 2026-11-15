"""The narrator's one sentence for tamper and tamper_cleared (CONTRACTS.md section 6, Tamper)."""
import json
import re

import pytest

from narrator import narrate as n

NOW = 1_763_149_512_000
DESK = {"nodes": [{"id": "unoq", "name": "Board"}, {"id": "pi5", "name": "Pi A"}, {"id": "pi5b", "name": "Pi B"},
                  {"id": "east", "name": "East beacon"}, {"id": "west", "name": "West beacon"}],
        "zones": [{"id": 1, "name": "Left", "still_alert_s": 10}, {"id": 2, "name": "Right", "still_alert_s": 10}],
        "hall": {"beacons": [{"node": "h", "id": "H", "xyz_m": None}, {"node": "j", "id": "J", "xyz_m": None}]}}
SQUARE = {"nodes": [{"id": "unoq"}, {"id": "pi5"}, {"id": "east"}, {"id": "west"}],
          "zones": [{"id": 1, "name": "Bed", "still_alert_s": 60}, {"id": 4, "name": "Bathroom", "still_alert_s": 10}]}
NEVER_SAID = re.compile(r"attack|burglar|thief|unplugged by|someone|who\b", re.IGNORECASE)


def ev(kind, t=NOW, id="e1", **info):
    return {"v": 2, "type": "event", "t": t, "seq": 1, "src": "live", "id": id, "kind": kind, "info": info}


@pytest.fixture
def layout(tmp_path):
    saved = dict(n.DEVICES)

    def use(doc):
        path = tmp_path / "nodes.json"
        path.write_text(json.dumps(doc))
        n.set_zones(n.load_zones(path))
        n.set_devices(n.load_devices(path))
    yield use
    n.set_devices(saved)


def test_on_the_desk_the_device_has_its_name_from_nodes_json(layout):
    layout(DESK)
    assert n.template("tamper", {"node": "east"}) == "The East beacon went quiet while the space was armed."
    assert n.template("tamper_cleared", {"node": "east"}) == "The East beacon is back."
    assert n.template("tamper", {"node": "pi5b"}) == "Pi B went quiet while the space was armed."
    assert n.template("tamper", {"node": "unoq"}) == "The Board went quiet while the space was armed."


def test_on_the_square_the_built_in_words_are_used(layout):
    layout(SQUARE)
    assert n.template("tamper", {"node": "east"}) == "The east beacon went quiet while the space was armed."
    assert n.template("tamper_cleared", {"node": "west"}) == "The west beacon is back."
    assert n.template("tamper", {"node": "pi5"}) == "The router went quiet while the space was armed."


def test_a_hall_beacon_reads_as_the_far_beacon_on_its_path(layout):
    layout(DESK)
    assert n.template("tamper", {"node": "h"}) == "The far beacon on path H went quiet while the space was armed."
    assert n.template("tamper_cleared", {"node": "j"}) == "The far beacon on path J is back."


def test_an_unknown_or_missing_device_is_still_one_plain_sentence(layout):
    layout(SQUARE)
    assert n.template("tamper", {"node": "h"}) == "A device went quiet while the space was armed."   # no hall in this file
    assert n.template("tamper", {}) == "A device went quiet while the space was armed."
    assert n.template("tamper_cleared", {}) == "The quiet device is back."


def test_the_sentences_never_say_why_or_who(layout):
    for doc in (DESK, SQUARE):
        layout(doc)
        for node in ("east", "west", "pi5", "unoq", "h", None):
            for kind in ("tamper", "tamper_cleared"):
                text = n.template(kind, {"node": node} if node else {})
                assert not NEVER_SAID.search(text) and not n.BANNED.search(text), text
                assert len(text.split()) <= n.MAX_WORDS


def narrator(sent, now):
    def no_model(messages):
        raise OSError("no model")
    nar = n.Narrator(no_model, sent.append, clock=lambda: now[0], sleep=lambda s: None)
    nar.warm = lambda: None
    return nar


def test_tamper_is_narrated_live_and_ranks_just_under_an_intrusion(layout):
    layout(DESK)
    assert "tamper" in n.EVENT_KINDS and "tamper_cleared" in n.EVENT_KINDS
    assert n.rank("intrusion") < n.rank("tamper") < n.rank("alert_on") < n.rank("enter")
    sent, now = [], [NOW]
    nar = narrator(sent, now)
    nar.observe(ev("enter", id="e1", zone=1))
    nar.observe(ev("tamper", id="e2", node="east"))        # both waiting: the tamper is the one said
    nar.narrate(nar.due(NOW))
    assert sent[-1]["text"] == "The East beacon went quiet while the space was armed."
    assert (sent[-1]["event_kind"], sent[-1]["event_id"], sent[-1]["source"]) == ("tamper", "e2", "template")


def test_the_eight_second_spacing_still_holds(layout):
    layout(DESK)
    sent, now = [], [NOW]
    nar = narrator(sent, now)
    nar.observe(ev("tamper", id="e1", node="east"))
    nar.narrate(nar.due(now[0]))
    now[0] = NOW + 5000
    nar.observe(ev("tamper_cleared", t=now[0], id="e2", node="east"))
    assert nar.due(now[0]) is None                          # 5 s after the last sentence: too soon
    now[0] = NOW + 7900
    assert nar.due(now[0]) is None
    now[0] = NOW + 8000
    nar.observe(ev("tamper_cleared", t=now[0], id="e3", node="east"))
    assert nar.due(now[0])["id"] == "e3"                    # 8 s after it: the fresh one goes out
    assert len(sent) == 1


def test_a_replay_on_the_screen_changes_nothing_for_live_narration(layout):
    """The screen replays from GET /history; the narrator only hears the brain's WebSocket. Rows of
    the past that reach it are not events, so nothing is said for them, and a live event that
    arrives meanwhile still goes out."""
    layout(DESK)
    sent, now = [], [NOW]
    nar = narrator(sent, now)
    for i in range(5):                                      # history rows are not events
        nar.observe({"t": NOW - 60_000 + i * 1000, "present": True, "zone": 2, "armed": True, "tamper": ["east"]})
        nar.observe({"v": 2, "type": "state", "t": NOW, "src": "replay", "tamper": ["east"]})
    assert nar.due(NOW) is None and sent == []
    nar.observe(ev("intrusion", id="e7", zone=1))
    nar.narrate(nar.due(NOW))
    assert sent[-1]["event_kind"] == "intrusion" and sent[-1]["event_id"] == "e7"


def test_the_fake_brain_says_the_same_sentences():
    from sim import fake, state
    texts, node = {}, None
    brain = state.Brain(fake.load_path("tamper"))
    for m in state.run(fake.load_path("tamper"), brain=brain):
        if m["type"] == "event" and m["kind"] in ("tamper", "tamper_cleared"):
            texts[m["kind"]], node = brain.narration["text"], m["info"]["node"]   # whichever device the layout's path unplugs
    assert texts == {"tamper": n.template("tamper", {"node": node}),
                     "tamper_cleared": n.template("tamper_cleared", {"node": node})}
    assert texts["tamper"].endswith("went quiet while the space was armed.")
