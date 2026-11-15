"""The brain on the gate with laptops as extra Wi-Fi lines: several lines cross the spot, one decides.

The layout is this folder's gate plus three laptop nodes and their pi5><node>:wifi links, each marked
"crosses_spot", "optional" and "classifier": false (CONTRACTS.md section 3). The laptop readings are
made up to the shape measured on the kit (issue #95, check h): about 9.3 a second, whole dBm, a
value kept for 1 to 2 s, half a dB of spread, 8 dB lower with a person on the spot. A stand-in, not
a measurement.
"""
import copy
import random

import pytest

from brain.alert import Tamper
from brain.core import Brain
from brain.health import Health
from brain.tests.gatefeed import GATE, LINKS, Feed
from brain.tests.simdata import T0_MS
from brain.tests.test_core import cmd
from brain.tests.test_gate import Kit, comings

LAPTOPS = ("laptop1", "laptop2", "laptop3")
LINES = tuple(f"pi5>{node}:wifi" for node in LAPTOPS)
WIFI, BLE = "pi5>pi5b:wifi", "pi5b>unoq:ble"


def fan(gate=GATE):
    doc = copy.deepcopy(gate)
    for i, node in enumerate(LAPTOPS):
        doc["nodes"].append({"id": node, "device": "laptop", "name": f"Laptop {i + 1}",
                             "xyz_m": [(1.0, -0.2, 1.6)[i], -0.2, 0.75], "roles": ["receiver"]})
        doc["links"].append({"id": f"pi5>{node}:wifi", "tx": "pi5", "rx": node, "kind": "wifi", "expected_hz": None,
                             "crosses_spot": True, "classifier": False, "optional": True})
    return doc


FAN = fan()


class Laptop:
    """One laptop's line: a reading every 1/9.3 s, the value drawn again every 1 to 2 s."""

    def __init__(self, node, t0, seed, level=-49.0, drop=8.0):
        self.link, self.rng, self.level, self.drop = f"pi5>{node}:wifi", random.Random(seed), level, drop
        self.on, self.next, self.value, self.until = True, float(t0), None, 0.0

    def due(self, t, depth):
        out = []
        while self.next <= t:
            if self.value is None or self.next >= self.until:
                self.value = round(self.rng.gauss(self.level - self.drop * depth, 0.5))
                self.until = self.next + self.rng.uniform(1000, 2000)
            if self.on:
                tick = int(self.next)
                out.append({"v": 2, "type": "rssi", "t": tick, "recv_t": tick, "seq": 0, "src": "sim",
                            "link": self.link, "kind": "wifi", "tx": "pi5", "rx": self.link[4:-5], "dbm": self.value})
            self.next += 1000 / 9.3
        return out


class FanKit(Kit):
    """The gate's made-up feed with laptops beside it. running: the laptops whose reader is on."""

    def __init__(self, seed=0, running=LAPTOPS, nodes=FAN, **feed):
        self.brain, self.feed = Brain(nodes=nodes), Feed(T0_MS, seed, **feed)
        self.rows, self.events, self._last = [], [], 0
        self.laptops = {node: Laptop(node, T0_MS, seed * 10 + i) for i, node in enumerate(LAPTOPS)}
        for node in LAPTOPS:
            self.laptops[node].on = node in running

    def _send(self, msg):
        for laptop in self.laptops.values():
            for reading in laptop.due(msg["recv_t"], self.feed.depth):
                self.brain.on_message(reading)
        super()._send(msg)


def row(state, link):
    return next((r for r in state["links"] if r["id"] == link), None)


def alarms(events):
    return [e["kind"] for _, e in events if e["kind"] in ("blind_on", "tamper", "drift", "recalibrating")]


@pytest.fixture(scope="module")
def kit():
    return FanKit().teach()


def test_the_layout_is_taken_and_the_laptop_lines_are_optional_not_classifier_links(kit):
    brain = kit.brain
    assert brain.optional == LINES and brain.presence_also == LINES
    assert brain.model_links == Brain(nodes=GATE).model_links            # the model sees the gate's own lines only
    assert brain.presence_line == WIFI and brain.presence_second == BLE  # Pi B's Wi-Fi line still decides
    assert not set(LINES) & set(brain.health.classifier_links) and not set(LINES) & set(brain.crossing)
    assert set(brain.tamper.links_of) == {"unoq", "pi5", "pi5b"}          # no laptop is watched for tamper
    assert not any(k in LINES for links in brain.tamper.links_of.values() for k in links)
    assert all(link in brain.base and brain.expected_hz[link] > 8 for link in LINES)   # heard at the baseline


def test_with_three_laptops_running_a_person_is_found_and_released_as_on_the_gate(kit):
    kit.play([(5, "nobody")])
    start, rows, events = kit.play([(8, "still")])
    found = next(t for t, s in rows if s["pred"] and s["pred"]["present"]) - start
    assert found <= 1500 and comings(events) == ["enter"]
    state = rows[-1][1]
    assert state["health"] == {"status": "ok", "blind": [], "reason": None}
    for link in LINES:                                                   # drawn: each has a row, down about 8 dB
        r = row(state, link)
        assert r["status"] == "ok" and 5 <= r["drop_db"] <= 11 and r["rate_hz"] > 7 and r["why"] == 0.0
    assert set(state["pred"]["why"]) <= set(kit.brain.model_links)
    start, rows, events = kit.play([(5, "nobody")])
    gone = next(t for t, s in rows if s["pred"] and not s["pred"]["present"]) - start
    assert gone <= 2000 and comings(events) == ["exit"] and alarms(kit.events) == []


def test_the_laptop_lines_never_raise_presence_on_their_own():
    kit = FanKit(seed=4).teach()
    kit.feed.drop = {}                                                   # from here only the laptops react to a person
    _, rows, events = kit.play([(4, "nobody"), (10, "still"), (4, "nobody")])
    assert max(row(s, LINES[0])["drop_db"] for _, s in rows) >= 6        # the laptop lines did fall ...
    assert comings(events) == [] and not any(s["pred"] and s["pred"]["present"] for _, s in rows)   # ... and brought nobody in


def test_a_laptop_line_holds_presence_while_the_wifi_line_is_silent_and_only_for_the_hold(kit):
    brain = kit.brain

    def visit(running):
        for node in LAPTOPS:
            kit.laptops[node].on = node in running
        kit.feed.drop = dict(kit.feed.drop, **{BLE: 0.0})                # the Bluetooth second opinion says nothing
        kit.play([(6, "nobody"), (6, "still")])
        assert brain._line_says() is True
        live = kit.feed.next[WIFI]
        kit.feed.next[WIFI] = float("inf")                               # Pi B's Wi-Fi readings stop arriving
        start, rows, _ = kit.play([(9, "still")])
        held = [t - start for t, s in rows if s["pred"] and s["pred"]["present"]]
        kit.feed.next[WIFI] = kit.feed.t
        kit.feed.drop = dict(kit.feed.drop, **{BLE: 8.0})
        kit.play([(6, "nobody")])
        assert live != float("inf")
        return max(held, default=0)

    assert visit(running=()) <= 2500                                     # no laptop: gone as soon as the line is silent
    held = visit(running=("laptop2",))                                   # one laptop is enough to hold ...
    assert 4000 <= held <= 7500                                          # ... for second_hold_s (5 s), never for ever
    for node in LAPTOPS:
        kit.laptops[node].on = True
    kit.play([(4, "nobody")])


def test_a_laptop_going_silent_mid_presence_changes_nothing_and_raises_nothing(kit):
    kit.brain.on_cmd(cmd("arm", on=True))
    kit.play([(5, "nobody"), (4, "still")])
    before = len(kit.events)
    for node in LAPTOPS:
        kit.laptops[node].on = False                                     # three lids close
    start, rows, events = kit.play([(12, "still")])
    assert all(s["pred"] and s["pred"]["present"] for _, s in rows)      # Pi B's line still has the person
    state = rows[-1][1]
    assert state["health"] == {"status": "ok", "blind": [], "reason": None} and "tamper" not in state
    assert [row(state, link)["status"] for link in LINES] == ["stale"] * 3     # said in its own row, and no more
    assert not any(e["kind"] in ("blind_on", "blind_off", "tamper", "exit") for _, e in kit.events[before:])
    _, rows, events = kit.play([(5, "nobody")])
    assert comings(events) == ["exit"] and rows[-1][1]["pred"]["present"] is False
    for node in LAPTOPS:
        kit.laptops[node].on = True                                      # the lids open again
    _, rows, events = kit.play([(6, "nobody")])
    assert [row(rows[-1][1], link)["status"] for link in LINES] == ["ok"] * 3
    assert not any(e["kind"].startswith(("tamper", "blind")) for _, e in events)
    kit.brain.on_cmd(cmd("arm", on=False))


def test_a_stale_laptop_line_holds_nothing():
    kit = FanKit(seed=5).teach()
    kit.feed.drop = dict(kit.feed.drop, **{BLE: 0.0})
    kit.play([(5, "nobody"), (6, "still")])
    for node in LAPTOPS:
        kit.laptops[node].on = False                                     # their last readings were 8 dB down
    kit.play([(3, "still")])
    kit.feed.next[WIFI] = float("inf")
    start, rows, _ = kit.play([(6, "still")])
    held = [t - start for t, s in rows if s["pred"] and s["pred"]["present"]]
    assert max(held, default=0) <= 2500                                  # old readings are no opinion


def test_with_no_laptop_at_all_the_kit_runs_as_the_plain_gate_and_pi_b_is_still_watched():
    kit = FanKit(seed=3, running=()).teach()                             # the baseline did not wait for them
    assert not set(LINES) & set(kit.brain.base)
    kit.brain.on_cmd(cmd("arm", on=True))
    start, rows, events = kit.play([(4, "nobody"), (6, "still"), (4, "nobody")])
    assert [e["kind"] for _, e in events if e["kind"] in ("enter", "exit", "intrusion", "tamper", "blind_on")] == \
        ["enter", "intrusion", "exit"]
    assert all(row(s, link) is None for _, s in rows for link in LINES)  # never heard: not listed
    assert rows[-1][1]["health"]["status"] == "ok"
    live = dict(kit.feed.next)
    kit.feed.next = {k: (float("inf") if "pi5b" in k else t) for k, t in live.items()}   # Pi B unplugged
    _, rows, events = kit.play([(8, "nobody")])
    assert [(e["kind"], e["info"]) for _, e in events if e["kind"].startswith("tamper")] == [("tamper", {"node": "pi5b"})]
    kit.feed.next = {k: kit.feed.t for k in LINKS}
    _, rows, events = kit.play([(8, "nobody")])
    assert [e["kind"] for _, e in events if e["kind"].startswith("tamper")] == ["tamper_cleared"]


def test_a_laptop_first_heard_after_the_baseline_is_drawn_and_has_no_say():
    kit = FanKit(seed=6, running=()).teach()
    kit.laptops["laptop1"].on = True
    kit.feed.drop = dict(kit.feed.drop, **{BLE: 0.0})
    _, rows, _ = kit.play([(4, "nobody"), (6, "still")])
    r = row(rows[-1][1], LINES[0])
    assert r["status"] == "ok" and r["base_dbm"] is None and r["drop_db"] is None
    assert kit.brain._optional_drop(LINES[0], kit.brain.window["end"]) is None
    kit.feed.next[WIFI] = float("inf")
    start, rows, _ = kit.play([(6, "still")])
    assert max((t - start for t, s in rows if s["pred"] and s["pred"]["present"]), default=0) <= 2500


def test_an_optional_lines_empty_level_follows_drift_while_nobody_is_there():
    kit = FanKit(seed=8).teach()
    link = LINES[0]
    base = kit.brain.base[link]
    for _ in range(3):
        kit.laptops["laptop1"].level -= 1.0                              # its empty level sinks 3 dB in three minutes
        kit.play([(60, "nobody")])
    assert abs(kit.brain.base[link] - (base - 3.0)) <= 1.0
    held = kit.brain.base[link]
    kit.play([(30, "still")])
    assert abs(kit.brain.base[link] - held) <= 0.5                       # frozen while somebody is there
    kit.play([(10, "nobody")])
    held = kit.brain.base[link]
    kit.laptops["laptop1"].level -= 8.0                                  # somebody stands in this line alone, beside the spot
    _, rows, events = kit.play([(90, "nobody")])
    assert abs(kit.brain.base[link] - held) <= 0.5                       # that is not its empty level either
    assert row(rows[-1][1], link)["drop_db"] >= 6 and comings(events) == []
    assert alarms(kit.events) == []


def test_health_and_tamper_treat_an_optional_link_as_one_that_may_be_silent():
    health = Health(["a>b:wifi", "a>c:wifi"], {"a>b:wifi": 25.0, "a>c:wifi": 9.3}, optional=["a>c:wifi"])
    assert health.classifier_links == ["a>b:wifi"]
    out = None
    for ms in range(0, 12000, 40):
        health.add("a>b:wifi", ms, -40)
        if ms < 4000:
            health.add("a>c:wifi", ms, -49)
        out = health.update(ms, "none")
        assert out["events"] == []
    assert out["health"] == {"status": "ok", "blind": [], "reason": None}
    assert [(r["id"], r["status"]) for r in out["links"]] == [("a>b:wifi", "ok"), ("a>c:wifi", "stale")]
    tamper = Tamper.from_nodes(FAN)
    assert tamper.links_of == Tamper.from_nodes(GATE).links_of


def test_the_plain_gate_and_every_layout_without_an_optional_link_are_as_before():
    brain = Brain(nodes=GATE)
    assert brain.optional == () and brain.presence_also == ()
    assert not any(lk.optional for lk in brain.health.links.values())
    assert brain.health.classifier_links == [k for k in brain.model_links if not k.endswith(">pi5b:wifi")
                                             and ">pi5b:" not in k]
    marked = fan()
    marked["links"][3]["optional"] = True                               # the presence line can't be switched off this way
    assert WIFI not in Brain(nodes=marked).optional and Brain(nodes=marked).presence_line == WIFI
