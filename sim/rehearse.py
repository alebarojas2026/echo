"""Demo rehearsal: play the whole demo through the real bus and brain and check every beat.

    python -m sim.rehearse          # PASS/FAIL per beat, exit 1 if any beat fails
    python -m sim.rehearse --desk   # the same for the 3-minute desk visit

The fake feed goes into the real bus code (bus.core.Bus), which stamps recv_t and forwards to
the real brain (brain.core.Brain); the brain's state and events are what the screen would get.
Bus and brain are joined in this process and time follows the feed, not the wall clock, so
about three minutes of room time (baseline, training, then the demo) plays in a few seconds.
The UDP and WebSocket hops are not exercised here.
"""
import json
import sys
import tempfile

from brain.core import Brain
from bus.core import Bus
from narrator import narrate
from narrator import recap as recaps

from . import fake
from .layout import LAYOUT
from .wire import encoder

START_MS = 1_763_149_500_000
FEED, SCREEN, NARRATOR = ("127.0.0.1", 50000), ("127.0.0.1", 50001), ("127.0.0.1", 50002)   # stand-in senders
# The layout from radio/nodes.json (sim/layout.py): zone centres, the tray spot, which zone alerts.
Z = LAYOUT.centres                                             # zone centres
TRAY = {"x": LAYOUT.tray[0], "y": LAYOUT.tray[1], "drop_db": 10}   # the metal tray at T1
TOUR = LAYOUT.tour()                                           # every zone once (the square: 3, 4, 2, 1)
STILL, CALM = LAYOUT.still_zone(), LAYOUT.calm_zone()          # where the alert fires; where nothing counts
WEST_EDGE = lambda zone: {"x": 0.0, "y": Z[zone][1]}           # noqa: E731  walking in from the west
EAST_EDGE = lambda zone: {"x": (LAYOUT.strip_m or LAYOUT.size_m)[0], "y": Z[zone][1]}   # noqa: E731


def walk(stops, start=0.0, move_s=2.0):
    """Waypoints that visit (zone, seconds to stand) in turn, walking move_s between them."""
    out, t = [], start
    for zone, stand_s in stops:
        x, y = Z[zone]
        out += [{"t": t + move_s, "x": x, "y": y}, {"t": t + move_s + stand_s, "x": x, "y": y}]
        t += move_s + stand_s
    return out, t


def training_walk():
    stops, end = walk([(z, 8) for z in TOUR] + [(STILL, 8)] + [(z, 6) for z in TOUR if z != STILL][::-1], start=6.0)
    person = [{"t": 0, "x": None}, {"t": 6.0, **WEST_EDGE(TOUR[0])}] + stops + [{"t": end + 0.1, "x": None}]
    return {"name": "rehearse-walk", "duration_s": end + 6, "person": person}


def demo_script():
    """The demo path, the commands the screen sends during it, and the beats to look for."""
    tour, end = walk([(z, 4) for z in TOUR] + [(STILL, 22)], start=5.0)   # ends standing in the alert zone
    still_from = end - 22
    wave, cam_off, leave = still_from + 15, still_from + 20, end
    tray_on, moved, tray_off, home, reset, finish = leave + 4, leave + 16, leave + 22, leave + 24, leave + 34, leave + 37
    path = {"name": "rehearsal", "duration_s": finish,
            "person": [{"t": 0, "x": None}, {"t": 5.0, **WEST_EDGE(TOUR[0])}] + tour
                      + [{"t": leave + 1, **EAST_EDGE(STILL)}, {"t": leave + 1.1, "x": None}],
            "waves": [{"t_on": wave, "t_off": wave + 2.5}],
            "camera": [{"t": 0, "state": "on"}, {"t": cam_off, "state": "off"}],
            "objects": [{**TRAY, "t_on": tray_on, "t_off": tray_off}],
            "router": [{"t": 0, "spot": "S-home"}, {"t": moved, "spot": "S-W30"}, {"t": home, "spot": "S-home"}]}
    commands = [(moved, "router_moved", {"spot": "S-W30"}), (home, "router_home", {}), (reset, "reset", {})]

    def pred(s, **want):
        return s["pred"] is not None and all(s["pred"][k] == v for k, v in want.items())

    def zone(n):
        return lambda s: pred(s, present=True, zone=n)

    def event(kind):
        return lambda e: e["kind"] == kind

    stand = {n: 5.0 + 2.0 + i * 6.0 for i, n in enumerate(TOUR)}   # when each tour stop begins
    beats = [   # (name, from s, to s, "state" or "event", what must show up)
        ("empty room", 0, 5, "state", lambda s: pred(s, present=False, kind="none")),
        ("walk in", 5, 11, "state", lambda s: pred(s, present=True, kind="person")),
        *[(f"tour: zone {n} {LAYOUT.names[n]}", stand[n], stand[n] + 4, "state", zone(n)) for n in TOUR],
        ("no-movement alert", still_from, wave, "event", event("alert_on")),
        ("wave check-in", wave, wave + 5, "event", event("checkin")),
        ("camera unplugged, radio only", cam_off, leave, "state",
         lambda s: s["cam"] == "off" and s["teacher"] is None and pred(s, present=True)),
        ("tray near the router", tray_on, moved, "state", lambda s: len(s["objects"]) > 0),
        ("advice to move the router", tray_on, moved, "state", lambda s: s["advice"] is not None),
        ("router moved", moved, home, "state", lambda s: s["router"] == "S-W30" and s["pred"] is None),
        ("router back home", home, reset, "state", lambda s: s["router"] == "S-home" and s["pred"] is not None),
        ("reset between judges", reset, finish, "state",
         lambda s: s["alert"]["state"] == "none" and s["checkin"] is None and s["narration"] is None),
        ("recap after the reset", reset, finish, "state", recap_shown),
    ]
    return path, commands, beats


def recap_shown(s) -> bool:
    """The end-of-demo recap is on the screen and fits the
    recap limits (section 6). With no model in the rehearsal it is the template recap."""
    n = s["narration"]
    return bool(n and n["source"] == "template" and recaps.problem(n["text"], [n["text"]], camera_off=True) is None
                and "router" in n["text"] and "zone" in n["text"])


def no_model(messages):
    raise ConnectionRefusedError("no model in the rehearsal")


def wander(zone: int, start: float, end: float, step_s: float = 1.5) -> list:
    """Waypoints that keep walking inside one zone (so it reads as moving), from start to end."""
    x, y = Z[zone]
    corners, out, t, i = [(x - 0.2, y - 0.2), (x + 0.2, y + 0.2)], [], start, 0
    while t <= end:
        out.append({"t": t, "x": corners[i % 2][0], "y": corners[i % 2][1]})
        t, i = t + step_s, i + 1
    return out


def desk_script():
    """The 3-minute desk visit in docs/desk-demo.md, at its times: the judge walks in at 0:20 and
    around, goes to the bathroom (the zone with the shortest still limit) at 0:45 and stands still until
    the alert, waves at 1:10, moves to a zone with no alert while the camera cable is pulled, and walks
    out at 2:10. Then armed mode: armed at 2:15 with nobody there, the judge steps back in at 2:20 (an
    intrusion), and it's disarmed at the end."""
    wave, cam_off, leave, arm, back, finish = 70.0, 95.0, 130.0, 135.0, 140.0, 160.0
    at = lambda zone, t: {"t": t, "x": Z[zone][0], "y": Z[zone][1]}   # noqa: E731
    around = [at(z, 22.0 + 3 * i) for i, z in enumerate(TOUR)]   # walk through every zone, then keep moving
    person = ([{"t": 0, "x": None}, {"t": 20.0, **WEST_EDGE(TOUR[0])}] + around
              + wander(CALM, 23.0 + 3 * len(TOUR), 43.0) + [at(STILL, 47.0), at(STILL, wave + 4), at(CALM, wave + 6)]
              + wander(CALM, wave + 7, leave - 2) + [{"t": leave, **EAST_EDGE(CALM)}, {"t": leave + 0.1, "x": None}]
              # armed at 2:15 with nobody there; the judge steps back in at 2:20: an intrusion
              + [{"t": back, **WEST_EDGE(TOUR[0])}, at(STILL, back + 2)] + wander(STILL, back + 3, finish - 6)
              + [{"t": finish - 4, **EAST_EDGE(STILL)}, {"t": finish - 3.9, "x": None}])
    path = {"name": "desk", "duration_s": finish, "person": person,
            "waves": [{"t_on": wave + 1, "t_off": wave + 3.5}],
            "camera": [{"t": 0, "state": "on"}, {"t": cam_off, "state": "off"}],
            "router": [{"t": 0, "spot": "S-home"}]}

    def pred(s, **want):
        return s["pred"] is not None and all(s["pred"][k] == v for k, v in want.items())

    beats = [
        ("nobody before the judge", 0, 20, "state", lambda s: pred(s, present=False)),
        ("judge walks in", 20, 45, "state", lambda s: pred(s, present=True, kind="person")),
        ("still in the bathroom", 45, wave, "state", lambda s: pred(s, present=True, zone=STILL, motion="still")),
        ("no-movement alert", 45, wave, "event", lambda e: e["kind"] == "alert_on"),
        ("wave check-in", wave, 90, "event", lambda e: e["kind"] == "checkin"),
        ("camera pulled, radio only", cam_off, leave, "state",
         lambda s: s["cam"] == "off" and s["teacher"] is None and pred(s, present=True, zone=CALM)),
        ("walks out: nobody is here", leave, arm, "state", lambda s: pred(s, present=False)),
        ("armed, nobody here", arm, back, "state", lambda s: s.get("armed") is True and pred(s, present=False)),
        ("intrusion while armed", back, back + 10, "event", lambda e: e["kind"] == "intrusion"),
        ("disarmed", finish - 4, finish, "event", lambda e: e["kind"] == "disarmed"),
    ]
    commands = [(arm, "arm", {"on": True}), (finish - 3, "arm", {"on": False})]
    return path, commands, beats


class Stack:
    """The real bus and the real brain, joined in one process, on the feed's clock."""

    def __init__(self, folder, seed: int = 0):
        self.now, self.seed = START_MS, seed
        self.states, self.events = [], []
        self.encode = encoder(0)   # one producer for the whole run; times are passed in absolute
        self.bus = Bus(sessions=folder, clock=lambda: self.now,
                       send=lambda data: self.brain.on_message(json.loads(data)))
        self.outbox = []   # commands the brain passes to the bus
        self.brain = Brain(sessions_dir=folder, to_bus=self.outbox.append)
        # The narrator's recap, as on the board: brain events in, a narration to the bus on reset.
        self.narrator = narrate.Narrator(no_model, self._narration, clock=lambda: self.now, sleep=lambda s: None)
        self.recap = recaps.Recap(self.narrator, no_model)

    def _narration(self, msg: dict) -> None:
        self.bus.handle(json.dumps(msg).encode(), NARRATOR)

    def _events(self) -> None:
        new = self.brain.pop_events()
        self.events += new
        for e in new:
            kept = self.recap.observe(e)
            if kept:
                self.recap.write(kept, e)

    def cmd(self, name: str, **args) -> None:
        """A command from the screen. As over real sockets, the bus hears it after the brain has
        handled it, so the bus's answer (the meta for record_start) arrives afterwards."""
        self.brain.on_cmd({"v": 2, "type": "cmd", "cmd": name, "args": args})
        while self.outbox:
            self.bus.handle(json.dumps(self.outbox.pop(0)).encode(), SCREEN)

    def play(self, path: dict, commands=()) -> int:
        """Feed one path through bus and brain, taking a state every 0.1 s. Returns its start, epoch ms."""
        t0, pending, ticks = self.now, sorted(commands, key=lambda c: c[0]), 0
        for e in fake.simulate(path, seed=self.seed):
            while pending and pending[0][0] <= e["t"]:
                _, name, args = pending.pop(0)
                self.cmd(name, **args)
            self.now = t0 + round(e["t"] * 1000)
            self.bus.handle(self.encode({**e, "t": t0 / 1000 + e["t"]}).encode(), FEED)
            if e["t"] * 10 >= ticks:
                ticks += 1
                self.states.append(self.brain.state())
                self._events()
        self.now = t0 + round(path["duration_s"] * 1000)
        return t0

    def calibrate(self) -> list:
        """Baseline, two recorded sessions (a walk and the tray) and training, as in the runbook."""
        self.cmd("baseline")
        self.play({"name": "rehearse-baseline", "duration_s": 24, "person": None})
        self.cmd("record_start", session="rehearse-walk", purpose="train", walker="sim")
        self.cmd("label_mode", mode="person")
        self.play(training_walk())
        self.cmd("record_stop")
        self.cmd("label_mode", mode="object")
        self.cmd("record_start", session="rehearse-tray", purpose="object", walker="sim")
        self.play({"name": "rehearse-tray", "duration_s": 20, "person": None, "label_mode": "object",
                   "objects": [{**TRAY, "t_on": 4}]})
        self.cmd("record_stop")
        self.cmd("label_mode", mode="off")
        self.cmd("train")
        self.states.append(self.brain.state())
        self._events()
        return [e["kind"] for e in self.events]


def rehearse(script=None, seed: int = 0) -> list:
    """Run the rehearsal. Returns [(beat name, passed, seconds until it showed or None)]."""
    path, commands, beats = script or demo_script()
    with tempfile.TemporaryDirectory() as folder:
        stack = Stack(folder, seed)
        setup = stack.calibrate()
        results = [("setup: baseline", "baseline_done" in setup, None), ("setup: training", "trained" in setup, None)]
        t0 = stack.play(path, commands)
        for name, start, end, where, shows in beats:
            items = stack.states if where == "state" else stack.events
            hits = [(m["t"] - t0) / 1000 - start for m in items
                    if start <= (m["t"] - t0) / 1000 < end and shows(m)]
            results.append((name, bool(hits), round(hits[0], 1) if hits else None))
    return results


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Play the demo through the real bus and brain, beat by beat.")
    ap.add_argument("--desk", action="store_true", help="the 3-minute desk visit (docs/desk-demo.md) instead")
    args = ap.parse_args(argv)
    results = rehearse(desk_script()) if args.desk else rehearse()
    for name, passed, shown in results:
        took = "" if shown is None else f"  shown after {shown:.1f} s"
        print(f"{'PASS' if passed else 'FAIL'}  {name}{took}")
    failed = [name for name, passed, _ in results if not passed]
    print(f"{len(results) - len(failed)} of {len(results)} beats passed" + (f"; failed: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
