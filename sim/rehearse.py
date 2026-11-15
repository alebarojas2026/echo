"""Demo rehearsal: play the whole demo through the real bus and brain and check every beat.

    python -m sim.rehearse          # PASS/FAIL per beat, exit 1 if any beat fails
    python -m sim.rehearse --desk   # the same for the 3-minute desk visit
    python -m sim.rehearse --lesson # the live lesson: teach left and right, then unplug the camera
    python -m sim.rehearse --aisle  # a crowded aisle: people walk past, a judge stands still
    python -m sim.rehearse --spot   # the hero path on a layout with one zone (a file with one zone plays this for --desk too)

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
from . import lesson as live
from .wire import encoder

START_MS = 1_763_149_500_000
FEED, SCREEN, NARRATOR = ("127.0.0.1", 50000), ("127.0.0.1", 50001), ("127.0.0.1", 50002)   # stand-in senders
# The layout from radio/nodes.json (sim/layout.py): zone centres, the tray spot, which zone alerts.
Z = LAYOUT.centres                                             # zone centres
TRAY = {"x": LAYOUT.tray[0], "y": LAYOUT.tray[1], "drop_db": 10}   # the metal tray at T1
TOUR = LAYOUT.tour()                                           # every zone once (the square: 3, 4, 2, 1)
STILL, CALM = LAYOUT.still_zone(), LAYOUT.calm_zone()          # where the alert fires; where nothing counts
LESSON = "desk-lesson"                                         # the session the desk visit's lesson records
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
    recap limits (section 6). With no model in the rehearsal it is the template recap.
    It tells of the router move, except on one spot: there the router is cabled and nothing says it moved."""
    n = s["narration"]
    return bool(n and n["source"] == "template" and recaps.problem(n["text"], [n["text"]], camera_off=True) is None
                and (len(LAYOUT.zones) == 1 or "router" in n["text"])
                and any(name.lower() in n["text"].lower() for name in LAYOUT.names.values()))


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
    """The hero path at the desk (AGENTS.md "Right now"), in one visit, with the commands the screen sends:
    found (the judge steps up and is seen), lesson (the camera labels them stepping left and right; the
    screen sends train while that recording is still open, as in the live lesson), unplug (the camera is
    pulled and the radio still follows them), still (they stand still on the right until the no-movement
    alert), then armed mode: they leave, the space is armed, stepping back in is an intrusion. They leave
    again, and with the space still armed a beacon is unplugged for 8 s: a tamper alert while the
    sensor is blind, cleared when the beacon is back. It is disarmed at the end.

    Left and right are two zones side by side from radio/nodes.json: the desk strip's Left and Right,
    or the square's two southern zones. Before the still beat nobody stands anywhere for long: on the
    desk both zones alert, and an alert stays on until a check-in or a reset."""
    left, right = sorted((CALM, STILL), key=lambda z: Z[z][0])
    assert LAYOUT.zones[right], "the right-hand zone needs a still_alert_s for the still beat"
    step_in, teach, train, cam_off, stop, still_from, leave, arm, back = 5, 10, 30, 38, 40, 48, 64, 68, 72
    gone, unplug, plug, finish = 82, 85, 93, 101
    # the beacon that is unplugged: the first node in the layout that only sends (no link ends at it)
    beacon = LAYOUT.prop_node()
    at = lambda zone, t: {"t": t, "x": Z[zone][0], "y": Z[zone][1]}   # noqa: E731
    person, t, side = [{"t": 0, "x": None}, {"t": step_in, **WEST_EDGE(left)}, at(left, 6)], 6, left
    while t + 4 <= still_from - 1:      # 3 s on a side, 1 s to cross, until the still beat
        person += [at(side, t + 3)]
        side = right if side == left else left
        person += [at(side, t + 4)]
        t += 4
    person += ([at(right, still_from), at(right, leave), {"t": leave + 1, **EAST_EDGE(right)}, {"t": leave + 1.1, "x": None},
                {"t": back - 0.1, "x": None}, {"t": back, **WEST_EDGE(left)}, at(left, back + 1)]
               + wander(left, back + 2, gone - 2) + [{"t": gone, **WEST_EDGE(left)}, {"t": gone + 0.1, "x": None}])
    path = {"name": "desk", "duration_s": finish, "person": person,
            "outages": [{"node": beacon, "t_on": unplug, "t_off": plug}],   # a beacon unplugged while armed
            "camera": [{"t": 0, "state": "on"}, {"t": cam_off, "state": "off"}],
            "router": [{"t": 0, "spot": "S-home"}]}
    commands = [(teach, "label_mode", {"mode": "person"}),
                (teach, "record_start", {"session": LESSON, "purpose": "train", "walker": "judge"}),
                (train, "train", {}), (stop, "record_stop", {}), (stop, "label_mode", {"mode": "off"}),
                (arm, "arm", {"on": True}), (finish - 3, "arm", {"on": False})]

    def pred(s, **want):
        return s["pred"] is not None and all(s["pred"][k] == v for k, v in want.items())

    def radio_only(zone):
        return lambda s: s["cam"] == "off" and s["teacher"] is None and pred(s, present=True, kind="person", zone=zone)

    def event(kind):
        return lambda e: e["kind"] == kind

    beats = [
        ("nobody before the judge", 0, step_in, "state", lambda s: pred(s, present=False)),
        ("found: the judge steps up", step_in, teach, "state", lambda s: pred(s, present=True, kind="person")),
        ("lesson: the camera labels the judge", teach, train, "state",
         lambda s: s["cam"] == "on" and s["teacher"] is not None and s["teacher"]["present"]),
        ("lesson: a model within 5 s of train", train, train + 5, "event", event("trained")),
        ("lesson: the model uses the lesson", train, cam_off, "state",
         lambda s: s["model"]["trained"] and LESSON in s["model"]["train_sessions"]),
        (f"unplug: radio only, on the left ({LAYOUT.names[left]})", stop, still_from, "state", radio_only(left)),
        (f"unplug: radio only, on the right ({LAYOUT.names[right]})", stop, leave, "state", radio_only(right)),
        ("still: standing still on the right", still_from, leave, "state",
         lambda s: pred(s, present=True, zone=right, motion="still")),
        ("still: no-movement alert", still_from, leave, "event", event("alert_on")),
        ("walks out: nobody is here", leave, arm, "state", lambda s: pred(s, present=False)),
        ("armed, nobody here", arm, back, "state", lambda s: s.get("armed") is True and pred(s, present=False)),
        ("intrusion while armed", back, back + 10, "event", event("intrusion")),
        ("tamper: a beacon unplugged while armed", unplug, unplug + 4, "event",
         lambda e: e["kind"] == "tamper" and e["info"] == {"node": beacon}),
        ("tamper: on the screen while the sensor is blind", unplug, plug, "state",
         lambda s: s.get("tamper") == [beacon] and s["health"]["status"] == "blind" and s["pred"] is None),
        ("tamper: cleared when the beacon is back", plug, plug + 3, "event",
         lambda e: e["kind"] == "tamper_cleared" and e["info"] == {"node": beacon}),
        ("disarmed", finish - 4, finish, "event", event("disarmed")),
    ]
    return path, commands, beats


def person_here(s) -> bool:
    """What the arrival screen shows "Found you." for: a prediction of a person present."""
    return bool(s["pred"] and s["pred"]["present"] and s["pred"]["kind"] == "person")


def aisle_passers(start: float, end: float, brush_at=None) -> list:
    """Passers-by from sim/paths/aisle.json, again and again from start until end, and one who
    brushes an arm tip over the edge at brush_at (the file's own brush is left out)."""
    walkers = [p for p in fake.load_path("aisle")["passers"] if not p.get("reach_m")]
    period = max(p["t_on"] for p in walkers) + 12.0
    out, t = [], start
    while t < end:
        out += [dict(p, t_on=t + p["t_on"]) for p in walkers if t + p["t_on"] < end]
        t += period
    if brush_at is not None:
        out.append({"t_on": brush_at, "from": "east", "lane_m": 0.25, "speed_mps": 1.0, "reach_m": 0.3})
    return out


def aisle_script():
    """A crowded aisle at the judging desk, camera unplugged: people walk past without stepping in
    and a neighbour stands 1 m beyond the east end the whole time. First nobody is in the area, then
    the space is armed with people still walking past, then a judge steps in and stands still in the
    alert zone while others pass. Walking past must never be a person here, an enter or an
    intrusion; the judge standing still must still get the no-movement alert."""
    arm, disarm, back, finish = 62.0, 112.0, 116.0, 156.0
    still_from = back + 1.5
    x, y = Z[STILL]
    w = (LAYOUT.strip_m or LAYOUT.size_m)[0]
    out = {"x": -0.4 if x < w / 2 else w + 0.4, "y": y}   # 0.4 m past the end nearer the alert zone
    person = [{"t": 0, "x": None}, {"t": back, **out}, {"t": still_from, "x": x, "y": y},
              {"t": finish - 4, "x": x, "y": y}, {"t": finish - 3, **out}, {"t": finish - 2.9, "x": None}]
    path = {"name": "aisle-rehearsal", "duration_s": finish, "person": person,
            "passers": aisle_passers(2.0, arm - 4, brush_at=40.0) + aisle_passers(arm + 2, disarm - 4, brush_at=90.0)
                       + aisle_passers(back + 4, finish - 6),
            "neighbours": [{"end": "east", "past_m": 1.0}],
            "camera": [{"t": 0, "state": "off"}], "router": [{"t": 0, "spot": "S-home"}]}
    commands = [(arm, "arm", {"on": True}), (disarm, "arm", {"on": False})]
    nobody = lambda s: not person_here(s)   # noqa: E731
    beats = [   # (name, from s, to s, kind, check); "every state" and "no event" must hold the whole time
        ("aisle: walking past is nobody (no Found you)", 2, arm, "every state", nobody),
        ("aisle: walking past is no enter", 2, arm, "no event", lambda e: e["kind"] == "enter"),
        ("aisle: armed", arm, arm + 2, "event", lambda e: e["kind"] == "armed"),
        ("aisle: armed, walking past is nobody", arm, disarm, "every state", nobody),
        ("aisle: armed, walking past is no intrusion", arm, disarm, "no event", lambda e: e["kind"] == "intrusion"),
        # Since the 3 s hold (#582) a short appearance while armed is a passed_by, not an intrusion: allowed, counted.
        ("aisle: armed, passed_by events while people walk past", arm, disarm, "count", lambda e: e["kind"] == "passed_by"),
        ("aisle: the judge steps in and is found", back, still_from + 4, "state", person_here),
        ("aisle: the judge stands still while others pass: no-movement alert", still_from + 9.5, still_from + 16,
         "event", lambda e: e["kind"] == "alert_on"),
    ]
    return path, commands, beats


def spot_script():
    """The hero path on a layout with one zone (the gate: one spot between Pi B and the desk), in one visit:
    found (the judge steps onto the spot), lesson (the camera labels them standing there and stepping off
    and on; train while the recording is open), unplug (the camera is pulled and the radio still knows they
    are there), still (they stand until the no-movement alert), then armed: they leave, the space is armed,
    somebody walks straight through (passed by), somebody steps on and stays (intrusion), and with nobody
    there a device is unplugged for 8 s (tamper, cleared when it is back). On a layout with a presence line,
    still armed: something is left standing in that line for 30 s (an object, never a person or an intrusion,
    and advice that names the line and no spot to move the router to), then taken away (the measured gain).
    Disarmed at the end.
    Nothing here names a side: there is one zone and the beats are about somebody being there or not."""
    spot = min(LAYOUT.zones)
    assert len(LAYOUT.zones) == 1 and LAYOUT.zones[spot], "the one-spot rehearsal needs a layout with one zone that has a still_alert_s"
    (x, y), limit = Z[spot], LAYOUT.zones[spot]
    step_in, teach, off, on, train, cam_off, stop = 5, 10, 18, 23, 30, 38, 40
    still_from = 42
    leave = still_from + limit + 6
    arm, through, back, gone = leave + 4, leave + 8, leave + 16, leave + 26
    unplug, plug, finish = gone + 3, gone + 11, gone + 19
    line = LAYOUT.presence_line
    thing_on, thing_off = finish - 2, finish + 28          # with a presence line: a thing left in it for 30 s
    if line:
        finish = thing_off + 14
    prop = LAYOUT.prop_node()
    here = lambda t, dx=0.0: {"t": t, "x": round(x + dx, 3), "y": y}          # noqa: E731
    away = lambda t: {"t": t, **WEST_EDGE(spot)}                               # noqa: E731
    out = lambda t: {"t": t, "x": None}                                        # noqa: E731
    person = [out(0), away(step_in), here(step_in + 1)]
    person += [here(t, 0.1 if i % 2 else -0.1) for i, t in enumerate(range(step_in + 2, off, 2))]   # shifting about on the spot
    person += [here(off), away(off + 1), out(off + 1.1), out(on - 1.1), away(on - 1), here(on)]    # off the spot and back
    person += [here(t, 0.1 if i % 2 else -0.1) for i, t in enumerate(range(on + 2, still_from - 1, 2))]
    person += [here(still_from), here(leave), away(leave + 1), out(leave + 1.1)]
    person += [out(through - 0.1), away(through), {"t": through + 1.5, **EAST_EDGE(spot)}, out(through + 1.6)]   # straight through
    person += [out(back - 0.1), away(back), here(back + 1), here(gone - 1), away(gone), out(gone + 0.1)]
    path = {"name": "spot", "duration_s": finish, "person": person, "teacher": "desk",
            "outages": [{"node": prop, "t_on": unplug, "t_off": plug}],
            "camera": [{"t": 0, "state": "on"}, {"t": cam_off, "state": "off"}],
            "router": [{"t": 0, "spot": "S-home"}]}
    if line:
        tx, ty = LAYOUT.in_the_line()
        path["objects"] = [{"x": tx, "y": ty, "drop_db": 5.0, "t_on": thing_on, "t_off": thing_off}]
    commands = [(teach, "label_mode", {"mode": "person"}),
                (teach, "record_start", {"session": LESSON, "purpose": "train", "walker": "judge"}),
                (train, "train", {}), (stop, "record_stop", {}), (stop, "label_mode", {"mode": "off"}),
                (still_from, "reset_alert", {}),   # the still beat starts from zero, whatever the lesson's standing did
                (arm, "arm", {"on": True}), (finish - 3, "arm", {"on": False})]

    def pred(s, **want):
        return s["pred"] is not None and all(s["pred"][k] == v for k, v in want.items())

    def event(kind):
        return lambda e: e["kind"] == kind

    name = LAYOUT.names[spot]
    beats = [
        ("nobody before the judge", 0, step_in, "state", lambda s: pred(s, present=False)),
        (f"found: the judge steps up ({name})", step_in, teach, "state",
         lambda s: pred(s, present=True, kind="person", zone=spot, zone_set=[spot]) and len(s["pred"]["probs"]) == 2),
        ("lesson: the camera labels the judge", teach, train, "state",
         lambda s: s["cam"] == "on" and s["teacher"] is not None and s["teacher"]["present"]),
        ("lesson: a model within 5 s of train", train, train + 5, "event", event("trained")),
        ("lesson: the model uses the lesson", train, cam_off, "state",
         lambda s: s["model"]["trained"] and LESSON in s["model"]["train_sessions"]),
        ("unplug: radio only, somebody is here", stop, still_from, "state",
         lambda s: s["cam"] == "off" and s["teacher"] is None and pred(s, present=True, kind="person", zone=spot)),
        ("still: standing still", still_from + 2, leave, "state", lambda s: pred(s, present=True, zone=spot, motion="still")),
        ("still: no-movement alert", still_from, leave, "event", event("alert_on")),
        ("walks out: nobody is here", leave + 1, arm, "state", lambda s: pred(s, present=False)),
        ("armed, nobody here", arm, through, "state", lambda s: s.get("armed") is True and pred(s, present=False)),
        ("passed by: a walk straight through", through, back, "event", event("passed_by")),
        ("intrusion: somebody who stays", back, gone, "event",
         lambda e: e["kind"] == "intrusion" and e["info"] == {"zone": spot}),
        ("tamper: a device unplugged while armed", unplug, unplug + 4, "event",
         lambda e: e["kind"] == "tamper" and e["info"] == {"node": prop}),
        ("tamper: on the screen, and never 'somebody'", unplug + 3, plug, "state",
         lambda s: s.get("tamper") == [prop] and not pred(s, present=True)),
        ("tamper: cleared when the device is back", plug, plug + 4, "event",
         lambda e: e["kind"] == "tamper_cleared" and e["info"] == {"node": prop}),
        ("disarmed", finish - 4, finish, "event", event("disarmed")),
    ]
    beats.append(("no intrusion from the walk through", through, back - 0.2, "no event", event("intrusion")))
    if line:
        disarmed = beats.pop(-2)
        beats += [
            ("thing left in the line: an object, nobody there", thing_on, thing_on + 10, "state",
             lambda s: pred(s, present=False, kind="object", zone=0)),
            ("thing: advice about the line, and no spot to move the router to", thing_on, thing_on + 10, "state",
             lambda s: bool(s["advice"]) and s["advice"]["link"] == line and s["advice"]["to_spot"] is None
             and s["advice"]["move_m"] == [0, 0] and "router" not in s["advice"]["text"].lower()),
            ("thing taken away: the gain is measured", thing_off, thing_off + 10, "event",
             lambda e: e["kind"] == "advice_result" and e["info"]["link"] == line
             and e["info"]["after_dbm"] - e["info"]["before_dbm"] >= 3),
            disarmed,
            ("the thing is never somebody: no enter, no intrusion", thing_on, finish, "no event",
             lambda e: e["kind"] in ("enter", "intrusion", "passed_by")),
        ]
    return path, commands, beats


def lesson_script():
    """The live lesson (sim/lesson.py): the commands the screen sends and the beats to look for.
    The model starts from nothing: only a baseline and an empty recording exist before it."""
    path = live.path()
    record, train, cam_off, stop, end = live.RECORD_S, live.TRAIN_S, live.CAM_OFF_S, live.STOP_S, live.END_S
    commands = [(record, "label_mode", {"mode": "person"}),
                (record, "record_start", {"session": live.SESSION, "purpose": "train", "walker": "sim"}),
                (train, "train", {}), (stop, "record_stop", {}), (stop, "label_mode", {"mode": "off"})]

    def learning(s):
        return (s["model"]["training"] or {}).get("lesson") or {}

    def radio_only(s):
        return s["cam"] == "off" and s["teacher"] is None and s["model"]["training"] is None and s["pred"] is not None

    beats = [
        ("lesson: no model while the first 20 s are recorded", record, train, "state",
         lambda s: s["model"]["trained"] is False and s["teacher"] is not None and s["teacher"]["present"]),
        ("lesson: a model within 5 s of train", train - 0.2, train + 5, "event", lambda e: e["kind"] == "trained"),
        ("lesson: the learning signal counts 10 decisions", train, cam_off, "state", lambda s: learning(s).get("of") == 10),
        ("lesson: the radio agrees with the camera 8 of 10", train, cam_off, "state", lambda s: learning(s).get("agree", 0) >= 8),
        ("lesson: fits again while the camera is on", train + live.REFIT_S, cam_off, "state",
         lambda s: learning(s).get("fits", 0) >= 2),
        ("teach, then unplug: one last fit", cam_off, cam_off + 5, "event", lambda e: e["kind"] == "trained"),
        ("teach, then unplug: radio only", cam_off + 3, end, "state", radio_only),
        ("recording stopped, the radio carries on", stop + 1, end, "state", radio_only),
    ]
    return path, commands, beats


def lesson_setup(stack) -> list:
    """Before a lesson: a baseline and a short recording of the empty space, and no model."""
    stack.cmd("baseline")
    stack.play({"name": "lesson-baseline", "duration_s": 24, "person": None})
    stack.cmd("record_start", session="lesson-empty", purpose="train", walker="sim")
    stack.play({"name": "lesson-empty", "duration_s": 12, "person": None})
    stack.cmd("record_stop")
    stack.states.append(stack.brain.state())
    stack._events()
    kinds = [e["kind"] for e in stack.events]
    return [("setup: baseline", "baseline_done" in kinds, None), ("setup: no model yet", "trained" not in kinds, None)]


def follows_unplugged(stack, t0, settle_s: float = 1.5, share: float = 0.8) -> tuple:
    """The "teach, then unplug" beat: with the camera off, the radio's zone is the side the person
    is standing on, in at least `share` of the decisions (the first settle_s of each stand left out)."""
    right = total = 0
    for start, end, zone in live.stands():
        if start < live.CAM_OFF_S + 3:
            continue
        for s in stack.states:
            if start + settle_s <= (s["t"] - t0) / 1000 < end and s["cam"] == "off":
                total += 1
                right += bool(s["pred"] and s["pred"]["present"] and s["pred"]["zone"] == zone)
    what = "knows somebody is there" if len(LAYOUT.zones) == 1 else "follows left and right"
    return (f"teach, then unplug: the radio {what} ({right} of {total} decisions)",
            total > 0 and right >= share * total, None)


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
        narrate.set_zones(narrate.load_zones())   # the narrator's zone words come from nodes.json, as on the board
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
            self.now = t0 + round(e["t"] * 1000)
            self.bus.handle(self.encode({**e, "t": t0 / 1000 + e["t"]}).encode(), FEED)
            while pending and pending[0][0] <= e["t"]:   # after the reading, so the brain's clock has reached it
                _, name, args = pending.pop(0)
                self.cmd(name, **args)
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


def rehearse(script=None, seed: int = 0, lesson: bool = False) -> list:
    """Run the rehearsal. Returns [(beat name, passed, seconds until it showed or None)].
    lesson: the live lesson instead (lesson_script), starting with no model."""
    path, commands, beats = script or (lesson_script() if lesson else demo_script())
    with tempfile.TemporaryDirectory() as folder:
        stack = Stack(folder, seed)
        if lesson:
            results = lesson_setup(stack)
        else:
            setup = stack.calibrate()
            results = [("setup: baseline", "baseline_done" in setup, None), ("setup: training", "trained" in setup, None)]
        t0 = stack.play(path, commands)
        for name, start, end, where, shows in beats:
            items = stack.states if where.endswith("state") else stack.events
            inside = [m for m in items if start <= (m["t"] - t0) / 1000 < end]
            hits = [(m["t"] - t0) / 1000 - start for m in inside if shows(m)]
            if where == "every state":   # it must hold in every state of the window
                results.append((name, bool(inside) and len(hits) == len(inside), None))
            elif where == "no event":    # it must never happen in the window
                results.append((name, not hits, None))
            elif where == "count":       # allowed any number of times: how many is the result
                results.append((name, True, len(hits)))
            else:
                results.append((name, bool(hits), round(hits[0], 1) if hits else None))
        if lesson:
            results.append(follows_unplugged(stack, t0))
    return results


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Play the demo through the real bus and brain, beat by beat.")
    ap.add_argument("--desk", action="store_true", help="the hero path at the desk instead: found, lesson, unplug, still, arm + intrusion")
    ap.add_argument("--lesson", action="store_true", help="the live lesson: teach left and right, then unplug")
    ap.add_argument("--aisle", action="store_true", help="a crowded aisle: people walk past, a judge stands still")
    ap.add_argument("--spot", action="store_true", help="the hero path on a layout with one zone: found, lesson, unplug, still, arm, passed by, intrusion, tamper")
    args = ap.parse_args(argv)
    one = len(LAYOUT.zones) == 1
    if args.spot and not one:
        print("--spot needs a layout with one zone in radio/nodes.json (python -m radio.use_layout gate)")
        return 2
    if one and not args.lesson:
        # One zone has no tour, no sides and no aisle strip: every one of those is the one-spot hero path.
        results = rehearse(spot_script())
    else:
        results = (rehearse(lesson=True) if args.lesson else rehearse(desk_script()) if args.desk
                   else rehearse(aisle_script()) if args.aisle else rehearse())
    for name, passed, shown in results:
        took = "" if shown is None else f"  {shown} seen" if isinstance(shown, int) else f"  shown after {shown:.1f} s"
        print(f"{'PASS' if passed else 'FAIL'}  {name}{took}")
    failed = [name for name, passed, _ in results if not passed]
    print(f"{len(results) - len(failed)} of {len(results)} beats passed" + (f"; failed: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
