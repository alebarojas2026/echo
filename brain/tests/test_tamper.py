"""Tamper while armed (issues #533 and #534): a silenced device is noticed, packet loss is not."""
import json
import random

from brain.alert import Tamper
from brain.core import NODES_JSON, Brain
from brain.tests.test_core import cmd

DOC = json.loads(NODES_JSON.read_text(encoding="utf-8"))
LINKS = [link["id"] for link in DOC["links"]]
T0 = 1_000_000


def of(node, doc=DOC):
    return [link["id"] for link in doc["links"] if node in (link["tx"], link["rx"])]


def run(seconds, silent=(), armed=True, rule=None, t0=T0, loss=0.0, burst=None, seed=0, arm_at=None, last=None,
        doc=DOC, dead=()):
    """10 ticks and 10 readings a second per link. silent: {node: (from_s, to_s)}. burst: (every_s, long_s)
    of total silence on every link. dead: {link: (from_s, to_s)}, single links that stop.
    Returns (rule, [(seconds, kind, node)], last_seen, end time)."""
    rule, rng, last, events = rule or Tamper.from_nodes(doc), random.Random(seed), dict(last or {}), []
    for i in range(int(seconds * 10)):
        now, s = t0 + i * 100, i / 10
        in_burst = burst and s >= burst[0] and (s % burst[0]) < burst[1]   # the first burst after one period
        for link in [link["id"] for link in doc["links"]]:
            off = any(a <= s < b and link in of(node, doc) for node, (a, b) in dict(silent).items())                 or any(a <= s < b for k, (a, b) in dict(dead).items() if k == link)
            if not off and not in_burst and rng.random() >= loss:
                last[link] = now
        on = armed if arm_at is None else s >= arm_at
        events += [(s, kind, info["node"]) for kind, info in rule.update(now, on, last)]
    return rule, events, last, t0 + int(seconds * 10) * 100


def test_a_node_silent_for_3_s_while_armed_raises_one_tamper_and_clears_2_s_after_it_is_back():
    rule, events, _, _ = run(20, silent={"east": (5, 10)})
    assert [(k, n) for _, k, n in events] == [("tamper", "east"), ("tamper_cleared", "east")]
    (t_on, _, _), (t_off, _, _) = events
    assert 7.9 <= t_on <= 8.2 and 11.9 <= t_off <= 12.3          # 3 s after it stopped; 2 s after it came back
    assert rule.silent == []


def test_not_armed_raises_nothing():
    rule, events, _, _ = run(20, silent={"east": (5, 15)}, armed=False)
    assert events == [] and rule.silent == []


def test_packet_loss_and_one_second_bursts_never_look_like_tamper():
    for seed in range(5):
        _, events, _, _ = run(120, loss=0.6, burst=(7, 1.0), seed=seed)       # a crowded hall
        assert events == [], (seed, events[:3])
    _, events, _, _ = run(30, loss=0.6, burst=(7, 1.0), silent={"west": (10, 15)}, seed=9)
    assert [(k, n) for _, k, n in events if k == "tamper"] == [("tamper", "west")]   # a real 5 s silence: exactly one


def test_a_device_that_is_back_is_cleared_even_when_most_of_its_packets_are_lost():
    for seed in range(5):                                                      # 75% loss: 2 or 3 readings a second get through
        _, events, _, _ = run(60, loss=0.75, burst=(7, 1.0), silent={"west": (10, 15)}, seed=seed)
        assert [(k, n) for _, k, n in events] == [("tamper", "west"), ("tamper_cleared", "west")], (seed, events)
        assert 16.9 <= events[1][0] <= 19.5, (seed, events)                    # about 2 s after it is back, and it stays cleared


def test_on_the_desk_layout_the_node_named_is_the_one_that_went_silent():
    from brain.tests.test_layout import desk
    doc, ids = desk()
    names = lambda events: [(k, n) for _, k, n in events]
    _, events, _, _ = run(20, silent={"pi5b": (5, 10)}, doc=doc)               # Pi B unplugged: its six links stop
    assert names(events) == [("tamper", "pi5b"), ("tamper_cleared", "pi5b")]
    # Pi A unplugged: the hotspot goes with it, so what Pi B hears stops arriving too. Pi B is
    # still heard by the board, so only Pi A is named.
    relayed = {k: (5, 10) for k in ids if k.endswith(("pi5b:ble", "pi5b:wifi"))}
    _, events, _, _ = run(20, silent={"pi5": (5, 10)}, dead=relayed, doc=doc)
    assert names(events) == [("tamper", "pi5"), ("tamper_cleared", "pi5")]
    # the board's Bluetooth reader stops but its Wi-Fi reading goes on: one reader down, no device named
    reader = {k: (5, 10) for k in ids if k.endswith("unoq:ble")}
    assert run(20, dead=reader, doc=doc)[1] == []


def test_the_two_times_are_settings_with_the_contract_values_as_defaults():
    rule = Tamper.from_nodes(DOC)
    assert (rule.silent_ms, rule.clear_ms) == (3000, 2000)
    quick = Tamper.from_nodes(DOC, silent_ms=1000, clear_ms=500)
    _, events, _, _ = run(20, silent={"east": (5, 10)}, rule=quick)
    assert [(s, k) for s, k, _ in events] == [(5.9, "tamper"), (10.5, "tamper_cleared")]


def test_disarming_clears_it_and_arming_with_a_node_already_silent_raises_it_at_once():
    rule, events, last, t = run(10, silent={"east": (2, 99)})
    assert [(k, n) for _, k, n in events] == [("tamper", "east")] and rule.silent == ["east"]
    assert rule.update(t, False, last) == [("tamper_cleared", {"node": "east"})] and rule.silent == []
    _, events, _, _ = run(12, silent={"east": (0, 99)}, arm_at=8)             # silent long before arming
    assert [(s, k, n) for s, k, n in events] == [(8.0, "tamper", "east")]


def test_two_nodes_at_once_each_raise_once_and_clear_one_at_a_time():
    rule, events, _, _ = run(30, silent={"east": (5, 12), "west": (5, 20)})
    kinds = [(k, n) for _, k, n in events]
    assert sorted(kinds[:2]) == [("tamper", "east"), ("tamper", "west")]
    assert kinds[2:] == [("tamper_cleared", "east"), ("tamper_cleared", "west")]
    assert [s for s, k, n in events if k == "tamper_cleared"][0] < 15           # east is back while west is still gone


def test_the_brain_raises_tamper_while_blind_lists_the_node_and_reset_clears_it():
    clock = [T0]
    brain = Brain(clock=lambda: clock[0])
    seen = []

    def tick(seconds, silent=()):
        for _ in range(int(seconds * 10)):
            clock[0] += 100
            for link in LINKS:
                if not any(link in of(node) for node in silent):
                    brain.on_message({"v": 2, "type": "rssi", "recv_t": clock[0], "src": "sim", "link": link, "dbm": -50})
            state = brain.state()
            seen.extend((e["kind"], e["info"]) for e in brain.pop_events() if e["kind"].startswith("tamper"))
        return state

    brain._set_baseline({link: -50.0 for link in LINKS}, {link: 10.0 for link in LINKS})
    assert "tamper" not in tick(3)
    brain.on_cmd(cmd("arm", on=True))
    state = tick(8, silent=["east"])
    assert state["tamper"] == ["east"] and seen == [("tamper", {"node": "east"})]
    assert state["health"]["status"] == "blind" and state["pred"] is None      # blind, and tamper still raised
    brain.on_cmd(cmd("reset"))                                                 # reset disarms: it clears
    state = tick(1, silent=["east"])
    assert "tamper" not in state and seen[-1] == ("tamper_cleared", {"node": "east"})
    tick(10, silent=["east"])
    assert len(seen) == 2                                                      # not armed: nothing more
