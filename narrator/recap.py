"""What the room noticed: a short recap at the end of each judge's demo, written on the board.

    python -m narrator.recap          # on the board: one recap of a sample demo, timed; nothing is sent

The narrator keeps the brain's events since the last reset. When the `reset` event arrives (the
screen's reset between judges), those events become a plain list of facts, the on-board model
turns them into at most 3 sentences and 45 words, and the result goes to the bus as a
`narration` with event_kind "recap". If the model is slow, unreachable, too long, adds a number
that is not in the facts or uses a banned word, a recap built from the same facts is sent instead.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

from narrator import narrate as n

MAX_WORDS, MAX_SENTENCES = 45, 3
TIMEOUT_S = 25.0     # 45 words is about three ordinary sentences on the board's model
MAX_TOKENS = 110
KEPT = ("enter", "zone_change", "exit", "alert_on", "intrusion", "armed", "checkin", "object_on", "object_off", "advice",
        "router_moved", "advice_result", "router_home", "cam_off", "blind_on", "blind_off")
SYSTEM = (
    "You write the recap shown on the screen at the end of a Wi-Fi sensing demo. "
    "You get a list of what the radio noticed, with times. Write at most 3 short sentences, "
    "40 words in total, in the past tense. Use only the facts given and no other numbers. "
    "Call a person someone. Reply with the recap only, on one line."
)


def _zone(z) -> str | None:
    return n.ZONES[z][0] if z in n.ZONES else None


def _clock(ms: int) -> str:
    return f"{ms // 60000}:{ms // 1000 % 60:02d}"


def _fact(kind: str, info: dict) -> str | None:
    zone, node = _zone(info.get("zone")), n.NODES.get(info.get("node"))
    before, after = n._dbm(info.get("before_dbm")), n._dbm(info.get("after_dbm"))
    if n.desk() or n.spot():   # in front of the desk: "on the left" or, with one spot, "at the desk"; "stepped up"
        side = (n._spot_words() if n.spot() else f"on the {zone.lower()}") if zone else None
        desk_facts = {
            "enter": (f"someone stepped up {side}" if side and not n.spot() else "someone stepped up to the desk"),
            "zone_change": f"someone moved over, now {side}" if side else None,
            "exit": "someone stepped away from the desk",
            "alert_on": f"no-movement alert {side}" if side else "no-movement alert",
            "intrusion": f"someone came in while armed, {side}" if side else "someone came in while armed",
        }
        if kind in desk_facts:
            return desk_facts[kind]
    return {
        "armed": "the space was armed",
        "intrusion": f"someone came in while armed, in the {zone} zone" if zone else "someone came in while armed",
        "enter": f"someone walked into the {zone} zone" if zone else "someone walked in",
        "zone_change": f"someone moved to the {zone} zone" if zone else None,
        "exit": "someone left the room",
        "alert_on": f"no-movement alert in the {zone} zone" if zone else "no-movement alert",
        "checkin": "a wave check-in was received",
        "object_on": f"a new object appeared near the {node}" if node else "a new object appeared in the room",
        "object_off": "the object was taken away",
        "advice": "the board advised moving the router",
        "router_moved": "the router was moved",
        "advice_result": (f"after the move the router's Wi-Fi went from {before} to {after} dBm"
                          if before is not None and after is not None else None),
        "router_home": "the router went back to its home spot",
        "cam_off": "setup ended and sensing carried on by radio alone",   # the screen never says camera once it is off
        "blind_on": "a radio link stopped reporting",
        "blind_off": "the radio links were all back",
    }.get(kind)


def facts(events: list) -> list:
    """One plain line per event worth telling: "0:12 someone walked into the Chair zone"."""
    out, t0 = [], None
    for e in events:
        line = _fact(e.get("kind"), e.get("info") or {}) if e.get("kind") in KEPT else None
        if line is None or not isinstance(e.get("t"), (int, float)):
            continue
        t0 = e["t"] if t0 is None else t0
        out.append(f"{_clock(int(e['t'] - t0))} {line}")
    return out


def _join(words: list) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def template(events: list) -> str | None:
    """A recap built straight from the events: at most 3 sentences and 45 words. None if nothing happened."""
    kinds = [e.get("kind") for e in events]
    info = {e["kind"]: e.get("info") or {} for e in events if e.get("kind")}   # the last of each kind
    zones = []
    for e in events:
        z = _zone((e.get("info") or {}).get("zone"))
        if e.get("kind") in ("enter", "zone_change") and z and z not in zones:
            zones.append(z)
    out = []
    if zones and n.spot():
        out.append("Someone stepped up to the desk.")
    elif zones and n.desk():
        out.append(f"Someone stood {_join([f'on the {z.lower()}' for z in zones])}.")
    elif zones:
        out.append(f"Someone visited the {_join(zones)} zone{'s' if len(zones) > 1 else ''}.")
    elif "enter" in kinds:
        out.append("Someone came into the room.")
    if "alert_on" in kinds:
        where = _zone(info["alert_on"].get("zone"))
        place = (f" {n._spot_words()}" if n.spot() else
                 f" on the {where.lower()}" if n.desk() else f" in the {where} zone") if where else ""
        alert = f"A no-movement alert fired{place}"
        out.append(alert + (" and a wave check-in answered it." if "checkin" in kinds else "."))
    elif "checkin" in kinds:
        out.append("A wave check-in was received.")
    if "intrusion" in kinds:
        out.append("While it was armed, someone came in.")
    before, after = n._dbm(info.get("advice_result", {}).get("before_dbm")), n._dbm(info.get("advice_result", {}).get("after_dbm"))
    if before is not None and after is not None:
        out.append(f"Moving the router took its Wi-Fi from {before} to {after} dBm.")
    elif "object_on" in kinds:
        out.append("A new object showed up in the radio picture.")
    elif "cam_off" in kinds:
        out.append("Setup ended and sensing carried on by radio alone.")
    return " ".join(out[:MAX_SENTENCES]) or None


def clean(text: str) -> str:
    """A model reply as plain ASCII on one line, ending in punctuation."""
    text = " ".join(text.translate(n.PUNCT).encode("ascii", "ignore").decode().split()).strip("\"'` ")
    return text + "." if text and text[-1] not in ".!?" else text


def problem(text: str, fact_lines: list, camera_off: bool) -> str | None:
    """Why a recap can't go on the screen, or None if it can."""
    if not text:
        return "empty"
    if len(text.split()) > MAX_WORDS:
        return "too long"
    if len(re.findall(r"[.!?]+(?:\s|$)", text)) > MAX_SENTENCES:
        return "too many sentences"
    if n.BANNED.search(text) or (camera_off and n.CAMERA.search(text)):
        return "banned word"
    if set(n.NUMBER.findall(text)) - set(n.NUMBER.findall(" ".join(fact_lines))):
        return "made-up number"
    return None


def prompt(fact_lines: list) -> list:
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": "What the radio noticed:\n" + "\n".join(fact_lines)}]


class Recap:
    """Collects events and writes the recap when the reset arrives.

    It shares the narrator's send, clock and seq counter, because both go out from one socket and
    the bus counts seq per socket. llm(messages) -> (text, model), as for the narrator.
    """

    def __init__(self, narrator: n.Narrator, llm, timeout_s: float = TIMEOUT_S):
        self.narrator, self.llm, self.timeout_s = narrator, llm, timeout_s
        self.events: list = []

    def observe(self, msg: dict) -> list | None:
        """Take any message from the brain. On a reset, returns the events to recap (None if there were none)."""
        if msg.get("type") != "event":
            return None
        if msg.get("kind") != "reset":
            self.events.append(msg)
            return None
        events, self.events = self.events, []
        return events if facts(events) else None

    def text(self, events: list) -> tuple:
        """(text, source, model, why) for one demo's events."""
        lines, fallback = facts(events), template(events)
        camera_off = self.narrator.cam == "off" or any(e.get("kind") == "cam_off" for e in events)
        try:
            raw, model = n.within(self.timeout_s, self.llm, prompt(lines))
        except TimeoutError:
            return fallback, "template", None, "model too slow"
        except Exception as e:
            return fallback, "template", None, f"model unreachable ({e})"
        text = clean(raw)
        why = problem(text, lines, camera_off)
        if why:
            return fallback, "template", None, f"{why}: {raw.strip()!r}"
        return text, "llm", model, "ok"

    def write(self, events: list, reset: dict) -> dict | None:
        """Build, send and return the recap narration for the demo that `reset` ended."""
        nar = self.narrator
        start = nar.clock()
        text, source, model, why = self.text(events)
        if not text:
            return None
        gen_ms = nar.clock() - start
        # Same 8 s spacing as every sentence, so the recap isn't sent right after one and the
        # next judge's first sentence can't replace it a second later.
        msg = nar.send_spaced(text=text, event_id=reset.get("id"), event_kind="recap", gen_ms=gen_ms,
                              source=source, model=model, src=reset.get("src", "live"))
        n.log(f"{reset.get('id')} recap of {len(events)} events -> {source} {gen_ms} ms ({why}): {text}")
        if nar.warm:   # the recap's prompt took the model's one cache slot: put the
            nar.warm()     # sentence prompt back before the next judge's first sentence
        return msg


# A demo as the brain reports it (no signal levels, so nothing here can turn into a made-up number).
def sample_demo() -> list:
    """A demo in the current zones (n.ZONES, from nodes.json): a tour of every zone, then the alert
    and a wave in the zone with the shortest still limit, the camera unplugged, and walking out."""
    zones = sorted(n.ZONES)
    limited = [z for z in zones if n.ZONES[z][1]]
    still = min(limited, key=lambda z: n.ZONES[z][1]) if limited else zones[-1]
    tour = [z for z in zones if z != still] + [still]
    return ([("enter", {"zone": tour[0]})] + [("zone_change", {"zone": z}) for z in tour[1:]]
            + [("alert_on", {"zone": still}), ("checkin", {"zone": still}), ("alert_off", {"zone": still}),
               ("cam_off", {}), ("exit", {"zone": still})])


def sample(now_ms: int) -> list:
    """The sample demo as brain events, 6 s apart, ending now."""
    demo = sample_demo()
    start = now_ms - 6000 * len(demo)
    return [{"v": 2, "type": "event", "t": start + 6000 * i, "seq": i + 1, "src": "sim", "id": f"s{i + 1}",
             "kind": kind, "info": info} for i, (kind, info) in enumerate(demo)]


def main(argv=None) -> int:
    """Write one recap of the sample demo with the board's model and print it. Exit 1 if the
    template had to be used (the reason is on stderr), so this doubles as the recap's gate."""
    p = argparse.ArgumentParser(description="One recap of a sample demo from the on-board model, timed.")
    p.add_argument("--llm", default=n.LLM_URL, help="llama-server base URL")
    p.add_argument("--timeout", type=float, default=TIMEOUT_S, help="seconds before the template is used")
    p.add_argument("--nodes", default=str(n.NODES_JSON), help="radio/nodes.json, for the zones")
    args = p.parse_args(argv)
    n.set_zones(n.load_zones(args.nodes))
    nar = n.Narrator(lambda m: ("", None), send=lambda msg: None)
    rc = Recap(nar, n.LlamaServer(args.llm, timeout_s=args.timeout, max_tokens=MAX_TOKENS), timeout_s=args.timeout)
    events = sample(nar.clock())
    reset = {"v": 2, "type": "event", "t": nar.clock(), "seq": 99, "src": "sim", "id": "reset", "kind": "reset", "info": {}}
    msg = rc.write(events, reset)
    print(json.dumps(msg), flush=True)
    print(f"recap: {msg['source']} in {msg['gen_ms']} ms (limit {args.timeout * 1000:.0f} ms), "
          f"{len(msg['text'].split())} words", file=sys.stderr, flush=True)
    return 0 if msg["source"] == "llm" else 1


if __name__ == "__main__":
    sys.exit(main())
