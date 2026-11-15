"""On a layout with a presence line: the steady still / moving word, and the no-movement alert that
follows it. The feeds are made up in the shape the kit showed (the line 25 times a second, under 1 dB of
wobble, a person 15 to 18 dB down); they show the rules, they are not measurements."""
import json
from pathlib import Path

from brain.alert import Watch
from brain.core import Brain
from brain.tests.gatefeed import GATE
from brain.tests.test_gate import alerts, cmd, cold_kit
from contracts import check

LINE = "pi5>pi5b:wifi"


def word(brain, t_ms, std):
    brain.window = {"end": t_ms, "long": {LINE: {"n": 50, "median": -65.0, "std": std}}}
    return brain._motion_says()


def held(**presence):
    brain = Brain(nodes=dict(GATE, presence=dict(GATE["presence"], **presence)))
    brain._here_t = -10_000    # somebody has been standing there for a while
    return brain


def test_one_sway_does_not_flip_the_word_and_stepping_about_does():
    brain = held(moving_spread_db=2.5, still_spread_db=1.5, motion_hold_s=1.5)
    t = 0
    for _ in range(50):                                   # standing: 0.5 dB
        t += 100
        assert word(brain, t, 0.5) == "still"
    for std in (3.2, 3.0, 2.8, 3.4, 0.9) * 4:             # sways of a few tenths of a second: never 1.5 s over the boundary
        t += 100
        assert word(brain, t, std) == "still", std
    said = []
    for _ in range(20):                                   # stepping about: over the boundary without a break
        t += 100
        said.append(word(brain, t, 3.5))
    assert said[:15] == ["still"] * 15 and said[15:] == ["moving"] * 5      # moving 1.5 s later
    for std in (2.0, 1.2, 2.2, 1.0, 1.6) * 4:             # between the two boundaries, or under for a moment: it stands
        t += 100
        assert word(brain, t, std) == "moving", std
    said = []
    for _ in range(20):
        t += 100
        said.append(word(brain, t, 0.6))
    assert said[:15] == ["moving"] * 15 and said[15:] == ["still"] * 5      # and still again 1.5 s after they stop
    assert word(brain, t + 100, None) == "still"          # too few readings: the word stands


def test_the_numbers_come_from_the_layout_file_and_have_defaults():
    plain = Brain(nodes=GATE)
    assert (plain.moving_spread_db, plain.still_share, plain.motion_hold_ms, plain.watch.line["return_ms"]) \
        == (2.0, 0.8, 1500, 8000)
    tuned = held(moving_spread_db=3.0, still_spread_db=1.5, motion_hold_s=0, checkin_return_s=5)
    assert (tuned.still_share, tuned.motion_hold_ms, tuned.watch.line) == (0.5, 0, {"link": LINE, "return_ms": 5000})
    assert [word(tuned, t, std) for t, std in ((100, 3.1), (200, 1.6), (300, 1.4))] == ["moving", "moving", "still"]
    for name in ("gate", "gate-3"):                       # the kit's files carry the chosen numbers and pass the contract
        doc = json.loads((Path(__file__).resolve().parents[2] / "radio" / "layouts" / f"{name}.json").read_text(encoding="utf-8"))
        assert check.errors(doc, "nodes") == []
        kit = Brain(nodes=doc)
        assert (kit.moving_spread_db, kit.still_share, kit.motion_hold_ms, kit.watch.line["return_ms"]) == (2.5, 0.6, 1500, 8000)


def person(motion="still"):
    return {"present": True, "kind": "person", "zone": 1, "zone_set": [1], "motion": motion}


NOBODY = {"present": False, "kind": "none", "zone": 0, "zone_set": [], "motion": None}


def line_watch(limit=10):
    watch = Watch({1: limit})
    watch.line = {"link": LINE, "return_ms": 8000}
    return watch


def feed(watch, t, pred, seconds):
    """Ten decisions a second; returns the time after them."""
    for _ in range(int(seconds * 10)):
        t += 100
        watch.on_pred(t, pred)
        block = watch.alert_block()
        # one decision: counting or check_on only on a person standing still
        assert block["state"] == "none" or (pred["present"] and pred["motion"] == "still"), (block, pred)
    return t


def kinds(watch):
    return [(kind, info.get("why")) for kind, info in watch.pop_events()]


def test_the_alert_ends_when_the_person_moves_and_never_shows_on_an_empty_spot():
    watch = line_watch()
    t = feed(watch, 0, person(), 12)
    assert kinds(watch) == [("alert_on", None)] and watch.alert_block()["state"] == "check_on"
    t = feed(watch, t, person("moving"), 0.1)             # the word is already held by the brain: one is enough
    assert kinds(watch) == [("alert_off", "moved")] and watch.alert_block() == {"state": "none", "zone": None, "still_s": 0, "limit_s": None}
    t = feed(watch, t, person(), 5)
    assert watch.alert_block()["state"] == "counting" and 4.8 <= watch.alert_block()["still_s"] <= 5.0
    t = feed(watch, t, person("moving"), 0.3)             # moving while counting: back to zero
    t = feed(watch, t, person(), 9)
    assert kinds(watch) == [] and watch.alert_block()["state"] == "counting"


def test_walking_away_ends_the_alert_as_left_and_stepping_aside_and_back_is_the_check_in():
    watch = line_watch()
    t = feed(watch, 0, person(), 12)
    assert kinds(watch) == [("alert_on", None)]
    t = feed(watch, t, NOBODY, 8)                         # gone: nothing shows at once (feed checks every tick) ...
    assert kinds(watch) == [] and watch.alerting
    t = feed(watch, t, NOBODY, 0.2)                       # ... and after checkin_return_s the alert is over: they left
    assert kinds(watch) == [("alert_off", "left")] and not watch.alerting and watch.checkin is None
    t = feed(watch, t, NOBODY, 60)
    assert kinds(watch) == [] and watch.alert_block()["state"] == "none"
    # the next person: the alert again, then a step out of the line and back
    t = feed(watch, t, person(), 12)
    assert kinds(watch) == [("alert_on", None)]
    t = feed(watch, t, NOBODY, 1.5)
    t = feed(watch, t, person(), 0.1)
    assert kinds(watch) == [("checkin", None), ("alert_off", "checkin")]
    assert watch.checkin == {"t": t, "link": LINE} and watch.alert_block()["state"] == "none"
    t = feed(watch, t, person(), 5)                       # the timer started again on their return
    assert watch.alert_block()["state"] == "counting" and 4.8 <= watch.alert_block()["still_s"] <= 5.1
    # one lost decision is not a step aside, and reset_alert says so on the event
    t = feed(watch, t, person(), 6)
    assert kinds(watch) == [("alert_on", None)]
    t = feed(watch, t, NOBODY, 0.1)
    t = feed(watch, t, person(), 1)
    assert kinds(watch) == [] and watch.alerting
    watch.reset_alert()
    assert kinds(watch) == [("alert_off", "reset")]


def test_a_layout_with_no_presence_line_keeps_its_alert_rules():
    watch = Watch({1: 10})
    t = 0
    for _ in range(120):
        t += 100
        watch.on_pred(t, person())
    for _ in range(3):                                    # a blip of moving neither resets nor clears there
        t += 100
        watch.on_pred(t, person("moving"))
    assert watch.alerting and [(k, i) for k, i in watch.pop_events()] == [("alert_on", {"zone": 1})]
    watch.reset_alert()
    assert watch.pop_events() == [("alert_off", {"zone": 1})]     # and no why


def test_on_the_whole_brain_alert_and_word_are_one_decision():
    """Cold on the gate, no model: stand still, step about, stand, step aside and back, walk away."""
    kit = cold_kit(seed=33)
    first = len(kit.rows)
    start, rows, events = kit.play([(14, "still")])
    assert alerts(events) == ["alert_on"] and rows[-1][1]["alert"]["state"] == "check_on"
    said = [s["pred"]["motion"] for _, s in rows if s["pred"]["present"]]
    assert set(said) == {"still"}                         # stepping on is not itself read as moving about
    _, rows, events = kit.play([(8, "moving")])           # real movement ends it within a few seconds
    off = [(t, e) for t, e in events if e["kind"] == "alert_off"]
    assert alerts(events) == ["alert_off"] and off[0][1]["info"] == {"zone": 1, "why": "moved"}
    assert (off[0][0] - rows[0][0]) / 1000 <= 3.5
    kit.play([(4, "still")])
    _, rows, events = kit.play([(14, "still")])
    assert alerts(events) == ["alert_on"]
    _, rows, events = kit.play([(1.5, "nobody"), (4, "still")])      # step aside and back
    assert alerts(events) == ["checkin", "alert_off"] and rows[-1][1]["checkin"]["link"] == LINE
    assert [e["info"].get("why") for _, e in events if e["kind"] == "alert_off"] == ["checkin"]
    _, rows, events = kit.play([(14, "still")])
    assert alerts(events) == ["alert_on"]
    _, rows, events = kit.play([(12, "nobody")])          # walk away
    assert alerts(events) == ["alert_off"] and [e["info"]["why"] for _, e in events if e["kind"] == "alert_off"] == ["left"]
    gone = [s for _, s in rows if s["pred"] and not s["pred"]["present"]]
    assert gone and all(s["alert"]["state"] == "none" for s in gone)          # never an alert on an empty spot
    states = [s for _, s in kit.rows[first:]]
    for s in states:                                      # the invariant the screen reads
        if s["pred"] and s["alert"]["state"] != "none":
            assert s["pred"]["present"] and s["pred"]["kind"] == "person" and s["pred"]["motion"] == "still", s
    bad = [err for s in states for err in check.errors(json.loads(json.dumps(s)), layout=GATE)]
    bad += [err for _, e in kit.events for err in check.errors(json.loads(json.dumps(e)), layout=GATE)]
    assert not bad, bad[:5]


def test_the_step_aside_seen_on_the_kit_is_a_check_in():
    """As it went on the kit: 12 dB down for 12 s (the alert at 10 s), out of the line for 3.5 s, back at 13 dB."""
    kit = cold_kit(seed=34)
    kit.feed.drop[LINE] = 12.0
    _, rows, events = kit.play([(12, "still")])
    assert alerts(events) == ["alert_on"] and rows[-1][1]["alert"]["state"] == "check_on"
    _, rows, events = kit.play([(3.5, "nobody")])
    assert alerts(events) == []                           # not yet "left": they may be stepping aside
    assert all(s["alert"]["state"] == "none" for _, s in rows if not s["pred"]["present"])
    kit.feed.drop[LINE] = 13.0
    start, rows, events = kit.play([(5, "still")])
    assert alerts(events) == ["checkin", "alert_off"]
    assert (next(t for t, e in events if e["kind"] == "checkin") - start) / 1000 <= 1.0
    last = rows[-1][1]
    assert last["checkin"]["link"] == LINE and last["alert"]["state"] == "counting" and 3.5 <= last["alert"]["still_s"] <= 5.0


def test_on_the_one_spot_a_wave_on_another_link_is_not_a_check_in():
    """Seen on the kit: during a stand with no alert up, the 8 cm line from Pi A to the board wobbled and
    raised a check-in. On a presence-line layout the only check-in is stepping out of the line and back."""
    desk_line = "pi5>unoq:wifi"
    for with_line in (True, False):
        watch = Brain(nodes=GATE).watch
        if not with_line:
            watch.line = None
        watch._person = True
        watch.checkin_rule.push = lambda *a: True          # the old wave rule says "a wave"
        watch.on_rssi({"recv_t": 1000, "link": desk_line, "dbm": -40.0})
        raised = [kind for kind, _ in watch._events if kind == "checkin"]
        assert raised == ([] if with_line else ["checkin"]), with_line
        assert (watch.checkin is None) == with_line
