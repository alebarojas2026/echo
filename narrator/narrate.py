"""Narrator: turns brain events into one plain sentence for the screen.

    python -m narrator.narrate                                   # live
    python -m narrator.narrate --once enter --info '{"zone": 2}'  # one sentence, printed only

Brain events in (WebSocket), one sentence from llama-server, a `narration` message out to the
bus (CONTRACTS.md sections 4-6). At most one sentence every 8 s, only for events up to 3 s old
when writing starts, at most 16 words. While a sentence is being written or the gap is running,
the most important waiting event is kept, not the newest. The event's template sentence is used when the model is slow (over 8 s),
unreachable, or says something it must not.
"""
from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import json
import re
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

WS_URL = "ws://127.0.0.1:8765/ws"
LLM_URL = "http://127.0.0.1:8091"
BUS = "127.0.0.1:5600"

GAP_MS = 8000         # at most one sentence every 8 s
MAX_AGE_MS = 3000     # only for events up to 3 s old
LLM_TIMEOUT_S = 8.0   # slower than this -> template
WARM_TIMEOUT_S = 120.0  # the warm-up writes the whole prompt into the cache; it may take longer
MAX_WORDS = 16

EVENT_KINDS = ("enter", "exit", "zone_change", "checkin", "object_on", "object_off", "advice",
               "advice_result", "router_moved", "router_home", "recalibrating", "cam_off", "cam_on",
               "cam_stalled", "alert_on", "alert_off", "blind_on", "blind_off", "trained",
               "baseline_done", "drift", "armed", "disarmed", "intrusion", "tamper", "tamper_cleared")
# Which waiting event to keep, most important first. Kinds not listed rank below all of these.
PRIORITY = ("intrusion", "tamper", "alert_on", "checkin", "cam_off", "advice_result", "object_on", "blind_on", "enter",
            "recalibrating", "trained", "zone_change", "exit")
NEVER = ("router_moved", "advice")   # the screen already says these itself
# Zone id -> (name, still_alert_s). Always read from radio/nodes.json (CONTRACTS.md section 3), at import
# and again in main for --nodes, so the sentences, the alert time and the prompt follow the layout.
# No zones are written here: if the file can't be read, sentences name no zone.
ZONES: dict = {}
NODES_JSON = Path(__file__).resolve().parent.parent / "radio" / "nodes.json"
NODES = {"unoq": "receiver", "pi5": "router", "pi5b": "second Pi", "east": "east beacon", "west": "west beacon"}
# Node id -> the device's name in radio/nodes.json ("East beacon"), and each hall beacon as "far beacon on path H".
# Loaded with the zones. A node with no name there falls back to NODES above.
DEVICES: dict = {}

# Things the screen must never say. The camera is added once it is off.
BANNED = re.compile(
    r"\b(fall|falls|fallen|falling|fell|security|surveillance|spy|spying|intruders?|npu"
    # identity
    r"|identity|identif\w*|recogni[sz]\w*|faces?|facial|names?|named|he|she|him|his|her|hers"
    r"|himself|herself|man|men|woman|women|boy|girl|guy|lady|child|kid|elderly"
    # health
    r"|health\w*|diagnos\w*|injur\w*|hurt|unconscious|collaps\w*|faint\w*|sick|ill|illness"
    r"|unwell|medical|emergency|ambulance|heart|breath\w*|stroke|seizure|pain|dizzy|accident"
    r"|dead|death|died|dying|asleep|sleep\w*|lying)\b"
    r"|through\s+(the\s+)?walls?",
    re.IGNORECASE,
)
CAMERA = re.compile(r"\bcam(era)?s?\b", re.IGNORECASE)
POOL = concurrent.futures.ThreadPoolExecutor(max_workers=2)  # model calls, so a hung one can be abandoned
NUMBER = re.compile(r"\d+(?:\.\d+)?")
PUNCT = str.maketrans("\u2018\u2019\u201c\u201d\u2013\u2014", "''\"\"--")


def log(*parts) -> None:
    print("narrator:", *parts, file=sys.stderr, flush=True)


def now_ms() -> int:
    return int(time.time() * 1000)


def rank(kind: str) -> int:
    """Lower is more important."""
    return PRIORITY.index(kind) if kind in PRIORITY else len(PRIORITY)


# ---------------------------------------------------------------- templates

def desk() -> bool:
    """The desk layout: its zones are the strip's left and right ends, so sentences say "on the left"
    and a person steps up to the desk instead of walking into a room."""
    return bool(ZONES) and all(name.lower() in ("left", "right") for name, _ in ZONES.values())


def spot() -> bool:
    """One zone in the file: one spot in front of the desk. There is no side to name, so sentences say
    where with the zone's own name when it reads as a place ("At the desk" -> "at the desk"), else "here"."""
    return len(ZONES) == 1


def _spot_words() -> str:
    name = next(iter(ZONES.values()))[0].strip().lower()
    return name if name.split(" ")[0] in ("at", "by", "in", "on") else "here"


def _zone(z) -> str | None:
    if z not in ZONES:
        return None
    if spot():
        return _spot_words()
    return f"on the {ZONES[z][0].lower()}" if desk() else f"zone {z} ({ZONES[z][0]})"


def _link(link) -> str | None:
    m = re.fullmatch(r"(\w+)>(\w+):\w+", str(link or ""))
    return f"{NODES.get(m[1], m[1])} to {NODES.get(m[2], m[2])}" if m else None


def _device(node) -> str | None:
    """A device as a sentence says it: "the East beacon", "Pi B", "the far beacon on path H". None if unknown."""
    name = DEVICES.get(node) or NODES.get(node)
    if not name:
        return None
    return name if name.startswith("Pi ") else f"the {name}"


def _dbm(v) -> int | None:
    return round(v) if isinstance(v, (int, float)) else None


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def template(kind: str, info: dict) -> str | None:
    """The fixed sentence for an event, or None for a kind we don't know."""
    zone = _zone(info.get("zone"))
    near = f" near the {NODES[info['node']]}" if info.get("node") in NODES else ""
    link = _link(info.get("link"))
    before, after = _dbm(info.get("before_dbm")), _dbm(info.get("after_dbm"))
    limit = info.get("limit_s") or ZONES.get(info.get("zone"), (None, None))[1]
    device = _device(info.get("node"))
    if spot():
        spot_sentences = {
            "alert_on": (f"No movement {zone or 'here'} for {f'{limit} seconds' if limit else 'a while'}. "
                         "Step aside and back to say you're okay."),
            # why the alert ended (the brain says so on a layout with a presence line): they moved, they left,
            # or they stepped aside and back (the check-in has its own sentence)
            **({"alert_off": "They moved, so the alert is cleared."} if info.get("why") == "moved" else {}),
            **({"alert_off": "They left while the alert was up."} if info.get("why") == "left" else {}),
            "object_on": "Something was left in the Wi-Fi line.",
            "object_off": "The obstruction in the Wi-Fi line is gone.",
            "advice": "Clear the obstruction or move the receiving device, then measure the Wi-Fi again.",
            "advice_result": (f"The Wi-Fi signal changed from {before} to {after} dBm."
                              if before is not None and after is not None else "The new Wi-Fi signal is being measured."),
        }
        if kind in spot_sentences:
            return spot_sentences[kind]
    if desk() or spot():   # in front of the desk: "on the left" or "at the desk", "stepped up", no rooms
        sentences = {
            "enter": (f"Someone is {zone}." if zone and spot() else
                      f"Someone just stepped up {zone}." if zone else "Someone just stepped up to the desk."),
            "exit": "Someone just stepped away from the desk.",
            "zone_change": f"Someone moved over, now {zone}." if zone else "Someone moved over.",
            "checkin": f"Check-in received {zone}." if zone else "Check-in received on the router link.",
            "recalibrating": "Recalibrating: please keep the space in front of the desk clear for 20 seconds.",
            "baseline_done": "Baseline captured; the empty space is now the radio reference.",
            "alert_on": (f"No movement {zone or 'here'} for {f'{limit} seconds' if limit else 'a while'}; "
                         "time to check in."),
            "alert_off": f"The alert {zone} is cleared." if zone else "The alert is cleared.",
            "intrusion": f"Someone is here while armed, {zone}." if zone else "Someone is here while armed.",
            "router_moved": "The router left its home spot, so tracking pauses.",
        }
        if kind in sentences:
            return sentences[kind]
    sentences = {
        "enter": f"Someone just walked into {zone or 'the room'}.",
        "exit": f"Someone just left the room from {zone}." if zone else "Someone just left the room.",
        "zone_change": f"Someone moved to {zone or 'another zone'}.",
        "checkin": f"Check-in received from {zone}." if zone else "Check-in received on the router link.",
        "armed": "Armed: this space should be empty now.",
        "disarmed": "Disarmed: people are expected here again.",
        # Tamper (section 6): what happened to the device, never why or who. The same words as the incident report.
        "tamper": f"{_cap(device or 'a device')} went quiet while the space was armed.",
        "tamper_cleared": f"{_cap(device or 'the quiet device')} is back.",
        "intrusion": f"Someone is here while armed, in {zone}." if zone else "Someone is here while armed.",
        "object_on": f"A new object{near or (' on the desk' if desk() or spot() else ' in the room')} is weakening the signal.",
        "object_off": f"The object{near} is gone.",
        "advice": "There is a new tip for placing the router.",
        "advice_result": (f"After the move, the router's Wi-Fi went from {before} to {after} dBm."
                          if before is not None and after is not None
                          else "The router move is done; the new signal is being measured."),
        "router_moved": "The router left its home spot, so zone tracking pauses.",
        "router_home": "The router is back on its home spot.",
        "recalibrating": "Recalibrating: please keep the room empty for 20 seconds.",
        "cam_off": "Setup is done; sensing now runs on radio alone.",
        "cam_on": "The camera is on to teach the radio model; no images are saved.",
        "cam_stalled": "The camera feed stalled, so teaching is paused.",
        "alert_on": (f"No movement in {zone or 'the room'} for "
                     f"{f'{limit} seconds' if limit else 'a while'}; time to check in."),
        "alert_off": f"The alert in {zone} is cleared." if zone else "The alert is cleared.",
        "blind_on": (f"Sensor blind on the {link} link; predictions pause." if link
                     else "Sensor blind: a radio link is failing, so predictions pause."),
        "blind_off": "All radio links are working again; predictions resume.",
        "trained": "Training is done; the radio model is now making predictions.",
        "baseline_done": "Baseline captured; the empty room is now the radio reference.",
        "drift": (f"The {link} link is drifting from its baseline." if link
                  else "The radio baseline is drifting; a new baseline may help."),
    }
    return sentences.get(kind)


# ---------------------------------------------------------------- the model

def load_zones(path=NODES_JSON) -> dict:
    """{zone id: (name, still_alert_s)} from nodes.json. {} if it can't be read: then no zone is named."""
    try:
        with open(path, encoding="utf-8") as f:
            return {int(z["id"]): (str(z["name"]), z.get("still_alert_s")) for z in json.load(f)["zones"]}
    except (OSError, ValueError, KeyError, TypeError) as e:
        log(f"zones from {path} not readable ({e}); sentences will name no zone")
        return {}


def set_zones(zones: dict) -> None:
    ZONES.clear()
    ZONES.update(zones)


def load_devices(path=NODES_JSON) -> dict:
    """{node id: name} from nodes.json: each node that has a name, and each hall beacon as
    "far beacon on path <its letter>". {} if the file can't be read."""
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        names = {str(n["id"]): str(n["name"]) for n in doc.get("nodes") or [] if n.get("name")}
        for b in (doc.get("hall") or {}).get("beacons") or []:
            names[str(b["node"])] = f"far beacon on path {b['id']}"
        return names
    except (OSError, ValueError, KeyError, TypeError) as e:
        log(f"device names from {path} not readable ({e}); using the built-in ones")
        return {}


def set_devices(names: dict) -> None:
    DEVICES.clear()
    DEVICES.update(names)


def load_crossing_wifi(path=NODES_JSON):
    try:
        with open(path, encoding="utf-8") as f:
            return {link["id"] for link in json.load(f)["links"]
                    if link.get("kind") == "wifi" and link.get("crosses_spot") is True}
    except (OSError, ValueError, KeyError, TypeError):
        return set()


set_devices(load_devices())
set_zones(load_zones())   # whoever imports this (the service, the recap, the rehearsal) gets the layout's zones
CROSSING_WIFI = load_crossing_wifi()


def _join(words: list) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def system() -> str:
    count = {1: "one zone", 2: "two zones", 3: "three zones", 4: "four zones"}.get(len(ZONES), f"{len(ZONES)} zones")
    where = (f"People stand on one spot in front of a desk. Say {_spot_words()}, never zone numbers and never a side. "
             "Describe recorded motion as moving or standing still. A person is never a dead zone. "
             "Wi-Fi across the gap is the main sensor; Bluetooth is a second opinion. "
             "An obstruction can be cleared or the receiving device moved; do not advise moving the cabled router. "
             if spot() else
             f"People stand in front of a desk, {_join([f'on the {n.lower()}' for _, (n, _) in sorted(ZONES.items())])}. "
             "Say on the left or on the right, never zone numbers. "
             if desk() else
             f"The room has {count}: {_join([f'zone {z} ({name})' for z, (name, _) in sorted(ZONES.items())])}. "
             if ZONES else "")
    return ("You write captions for the screen of a Wi-Fi sensing demo. " + where +
            "Rewrite the facts as one short, friendly sentence of at most 12 words. "
            "Use only the facts given. Call a person someone. Say no movement when nobody moves. "
            "Reply with the sentence only.")


def example_zone() -> int | None:
    """The zone the prompt's example and the warm-up use: 2 if the layout has it, else its first. None with no zones."""
    return (2 if 2 in ZONES else min(ZONES)) if ZONES else None


def examples() -> tuple:
    z = example_zone()
    name = ZONES[z][0] if ZONES else ""
    first = (("enter", "Someone just walked into the room.", "Someone just stepped into the room.")
             if not ZONES else
             ("enter", f"Someone is {_spot_words()}.", "Someone just stepped up to the desk.")
             if spot() else
             ("enter", f"Someone just stepped up on the {name.lower()}.", f"Someone stepped up, on the {name.lower()} side.")
             if desk() else
             ("enter", f"Someone just walked into zone {z} ({name}).", f"Someone just stepped into zone {z}, by the {name.lower()}."))
    if spot():
        return (first, ("advice_result", "The Wi-Fi signal changed from -71 to -63 dBm.",
                        "The Wi-Fi signal improved from -71 to -63 dBm."))
    return (first,
            ("advice_result", "After the move, the router's Wi-Fi went from -71 to -63 dBm.",
             "Moving the router lifted its Wi-Fi from -71 to -63 dBm."))


def prompt(kind: str, facts: str) -> list[dict]:
    """Chat messages for one event. Everything before the last message never changes,
    so llama-server keeps it cached and only the event itself is new work."""
    msgs = [{"role": "system", "content": system()}]
    for k, f, s in examples():
        msgs.append({"role": "user", "content": f"Event: {k}. Facts: {f}"})
        msgs.append({"role": "assistant", "content": s})
    msgs.append({"role": "user", "content": f"Event: {kind}. Facts: {facts}"})
    return msgs


class LlamaServer:
    """llama-server's OpenAI-style chat endpoint. Call it with chat messages;
    it returns (text, model name). A reply cut off by max_tokens comes back empty."""

    def __init__(self, url: str = LLM_URL, timeout_s: float = LLM_TIMEOUT_S, max_tokens: int = 40):
        self.url = url.rstrip("/") + "/v1/chat/completions"
        self.timeout_s, self.max_tokens = timeout_s, max_tokens

    def __call__(self, messages: list[dict]) -> tuple[str, str | None]:
        body = {"messages": messages, "max_tokens": self.max_tokens, "temperature": 0.2,
                "stop": ["\n"], "cache_prompt": True}
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
            reply = json.load(r)
        choice = reply["choices"][0]
        text = "" if choice.get("finish_reason") == "length" else choice["message"]["content"] or ""
        return text, reply.get("model")


def within(timeout_s: float, fn, *args):
    """fn(*args), or TimeoutError if it takes longer than timeout_s."""
    future = POOL.submit(fn, *args)
    try:
        return future.result(timeout=timeout_s)
    except concurrent.futures.TimeoutError:
        # Still waiting for a free worker: never send it. llama-server has one slot, so a call
        # for an event that is already gone would only hold up the next sentence.
        future.cancel()
        raise TimeoutError(f"no reply in {timeout_s:g} s") from None


class Warmer:
    """Keeps the sentence prompt cached in llama-server's single slot.

    kick() starts one warm-up on a background thread, unless one is already running. It retries
    until the model answers, because right after boot llama-server is still loading the model
    (connection refused, or HTTP 503) and a single try would leave the cache cold. A cold prompt
    can take longer than the 8 s a sentence gets, so the warm-up has its own, longer timeout.
    Kicked at start, after the recap (its prompt replaces the cached one) and whenever a
    sentence call fails (llama-server may have restarted and lost the cache).
    """

    def __init__(self, llm, retry_s: float = 2.0, give_up_s: float = 300.0,
                 sleep=time.sleep, clock=time.monotonic):
        self.llm, self.retry_s, self.give_up_s = llm, retry_s, give_up_s
        self.sleep, self.clock = sleep, clock
        self._busy = threading.Lock()

    def kick(self) -> bool:
        """Start a warm-up in the background. False if one is already running."""
        if not self._busy.acquire(blocking=False):
            return False
        threading.Thread(target=self._run_and_release, daemon=True).start()
        return True

    def _run_and_release(self) -> None:
        try:
            self.run()
        finally:
            self._busy.release()

    def run(self) -> bool:
        """Warm up now, retrying until the model answers or give_up_s has passed."""
        start = self.clock()
        while True:
            try:
                self.llm(prompt("enter", template("enter", {"zone": example_zone()})))
                log("model warm")
                return True
            except Exception as e:
                if self.clock() - start + self.retry_s > self.give_up_s:
                    log("warm-up gave up:", e)
                    return False
                log("warm-up failed, retrying:", e)
                self.sleep(self.retry_s)


def clean(text: str) -> str:
    """The first sentence of a model reply, plain ASCII, ending in punctuation."""
    text = text.translate(PUNCT).encode("ascii", "ignore").decode().strip()
    text = re.split(r"(?<=[.!?])[\"'`]*\s", text, maxsplit=1)[0]
    text = text.strip().strip("\"'`").strip()
    if text and text[-1] not in ".!?":
        text += "."
    return text


def problem(text: str, facts: str, camera_off: bool) -> str | None:
    """Why a sentence can't go on the screen, or None if it can."""
    if not text:
        return "empty"
    if len(text.split()) > MAX_WORDS:
        return "too long"
    if BANNED.search(text) or (camera_off and CAMERA.search(text)):
        return "banned word"
    if set(NUMBER.findall(text)) - set(NUMBER.findall(facts)):
        return "made-up number"
    if spot():
        if facts.startswith("Someone") and re.search(r"\bobject\b|dead.?zone", text, re.I):
            return "person described as an obstruction"
        move_router = r"\b(?:move|moved|moving) (?:the )?(?:router|Pi A)\b"
        if re.search(move_router, text, re.I) and not re.search(move_router, facts, re.I):
            return "unrecorded router move"
    return None


# ---------------------------------------------------------------- narrator

class Narrator:
    """Picks which events to narrate and builds the narration messages.

    llm(messages) -> (text, model) and send(msg) are injected, so tests can
    use fakes. clock() returns epoch ms; monotonic() returns elapsed seconds.
    """

    def __init__(self, llm, send, clock=now_ms, timeout_s=LLM_TIMEOUT_S,
                 gap_ms=GAP_MS, max_age_ms=MAX_AGE_MS, sleep=time.sleep,
                 monotonic=time.monotonic):
        self.llm, self.send, self.clock, self.sleep = llm, send, clock, sleep
        self.monotonic = monotonic
        self.timeout_s, self.gap_ms, self.max_age_ms = timeout_s, gap_ms, max_age_ms
        self.warm = None          # called when a model call fails (a Warmer's kick), if set
        self.pending = None       # the most important event not yet narrated
        self.state = None         # the latest existing state, used only to ground event wording
        self.cam = None           # on | off | stalled, from the brain
        self.seq = 0
        self.last_start_ms = None   # when the last sentence started being written
        self.last_sent_ms = None
        # narrate() and the recap (narrator/recap.py) run on their own threads and share the
        # gap, seq and socket: whoever sends holds this from the gap wait through the send.
        self.lock = threading.Lock()

    def observe(self, msg: dict) -> None:
        """Take any message from the brain."""
        if msg.get("type") == "state":
            self.state = msg
            if "cam" in msg:
                self.cam = msg["cam"]
            if spot() and self.pending and self.pending["kind"] == "object_on" and not self._current_object(msg.get("t")):
                self.pending = None
        elif msg.get("type") == "event" and msg.get("kind") == "reset":
            self.pending = None   # a new judge: the last demo's waiting event is not said, the recap is next
            self.state = None
        elif msg.get("type") == "event" and msg.get("kind") in EVENT_KINDS:
            if spot() and msg["kind"] == "object_on" and self._current_person(msg.get("t")):
                return
            if msg["kind"] in ("cam_off", "cam_on"):
                self.cam = msg["kind"][4:]
            if msg["kind"] in NEVER:
                return
            waiting = self.pending
            # A waiting event gives way to one at least as important, or once it is too old to be
            # narrated anyway. A minor event never pushes out a key one that can still be said.
            if (waiting is None or rank(msg["kind"]) <= rank(waiting["kind"])
                    or not self._fresh(waiting, msg.get("t"))):
                self.pending = msg

    def _current_person(self, now):
        state = self.state or {}
        pred = state.get("pred") or {}
        t = state.get("t")
        return (isinstance(t, (int, float)) and isinstance(now, (int, float)) and 0 <= now - t <= self.max_age_ms
                and pred.get("present") is True and pred.get("kind") == "person")

    def _current_object(self, now):
        state = self.state or {}
        pred, t = state.get("pred") or {}, state.get("t")
        return (isinstance(t, (int, float)) and isinstance(now, (int, float)) and 0 <= now - t <= self.max_age_ms
                and pred.get("present") is False and pred.get("kind") == "object"
                and any(link.get("id") in CROSSING_WIFI and link.get("status") == "ok"
                        and isinstance(link.get("drop_db"), (int, float)) and link["drop_db"] >= 3
                        for link in state.get("links", [])))

    def _fresh(self, event: dict, now) -> bool:
        t = event.get("t")
        return isinstance(t, (int, float)) and isinstance(now, (int, float)) and now - t <= self.max_age_ms

    def due(self, now: int) -> dict | None:
        """The pending event if it may be narrated now. Drops it once it is too old."""
        event = self.pending
        if event is None:
            return None
        if spot() and event["kind"] == "object_on" and not self._current_object(now):
            self.pending = None
            return None
        if not self._fresh(event, now):
            self.pending = None
            return None
        # The gap runs from when the last sentence started being written, so a slow model
        # does not stretch it: a 6 s sentence still leaves room for one every 8 s.
        if self.last_start_ms is not None and now - self.last_start_ms < self.gap_ms:
            return None
        self.pending = None
        self.last_start_ms = now
        return event

    def sentence(self, event: dict) -> tuple[str, str, str | None, str]:
        """(text, source, model, why) for one event."""
        facts = template(event["kind"], event.get("info") or {})
        if spot() and event["kind"] in ("enter", "zone_change") and self._current_person(self.clock()):
            motion = {"still": "standing still", "moving": "moving"}.get(self.state["pred"].get("motion"))
            if motion:
                facts = f"Someone is {_spot_words()}, {motion}."
        try:
            raw, model = within(self.timeout_s, self.llm, prompt(event["kind"], facts))
        except TimeoutError:
            self._rewarm()
            return facts, "template", None, "model too slow"
        except Exception as e:
            self._rewarm()
            return facts, "template", None, f"model unreachable ({e})"
        text = clean(raw)
        why = problem(text, facts, self.cam == "off")
        if why:
            return facts, "template", None, f"{why}: {raw.strip()!r}"
        return text, "llm", model, "ok"

    def _rewarm(self) -> None:
        if self.warm:
            self.warm()

    def narrate(self, event: dict) -> dict:
        """Build, send and return the narration for one event."""
        start = self.monotonic()
        text, source, model, why = self.sentence(event)
        gen_ms = round((self.monotonic() - start) * 1000)
        msg = self.send_spaced(text=text, event_id=event.get("id"), event_kind=event["kind"],
                               gen_ms=gen_ms, source=source, model=model, src=event.get("src", "live"))
        log(f"{event.get('id')} {event['kind']} -> {source} {gen_ms} ms ({why}): {text}")
        return msg

    def send_spaced(self, src: str, **fields) -> dict:
        """Send one narration no sooner than gap_ms after the last one, and return it.
        A quick sentence after a slow one waits its turn: the screen gets one per 8 s."""
        with self.lock:
            if self.last_sent_ms is not None:
                wait_ms = self.last_sent_ms + self.gap_ms - self.clock()
                if wait_ms > 0:
                    self.sleep(wait_ms / 1000)
            t = self.clock()
            self.seq += 1
            msg = {"v": 2, "type": "narration", "t": t, "seq": self.seq, "src": src, **fields}
            self.send(msg)
            self.last_sent_ms = t
            return msg

    def step(self) -> dict | None:
        event = self.due(self.clock())
        return self.narrate(event) if event else None


# ---------------------------------------------------------------- transport

async def brain_messages(url: str = WS_URL):
    """Every message from the brain's WebSocket, as dicts. Reconnects forever."""
    import websockets

    while True:
        try:
            async with websockets.connect(url) as ws:
                log("connected to", url)
                async for raw in ws:
                    try:
                        yield json.loads(raw)
                    except ValueError:
                        continue
        except (OSError, websockets.exceptions.WebSocketException) as e:
            log("brain not reachable, retrying:", e)
        await asyncio.sleep(1.0)


def udp_sender(bus: str = BUS):
    """send(msg): one JSON datagram to the bus."""
    host, port = bus.rsplit(":", 1)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(msg: dict) -> None:
        try:
            sock.sendto(json.dumps(msg, separators=(",", ":")).encode(), (host, int(port)))
        except OSError as e:
            log("bus send failed:", e)

    return send


async def serve(messages, narrator: Narrator, poll_s: float = 0.1, recap=None) -> None:
    """Feed brain messages to the narrator and narrate whenever an event is due.
    Returns once the messages end and nothing is left to narrate.
    recap (narrator/recap.py), if given, writes the end-of-demo recap when a reset arrives."""
    recaps = []

    async def feed():
        async for msg in messages:
            narrator.observe(msg)
            events = recap.observe(msg) if recap else None
            if events:   # written off the loop, so events keep flowing meanwhile
                recaps.append(asyncio.create_task(asyncio.to_thread(recap.write, events, msg)))
        await asyncio.gather(*recaps)

    feeder = asyncio.create_task(feed())
    while not (feeder.done() and narrator.pending is None):
        event = narrator.due(narrator.clock())
        if event:
            await asyncio.to_thread(narrator.narrate, event)
        else:
            await asyncio.sleep(poll_s)
    await feeder


def warm_up(llm) -> None:
    """One throwaway request so llama-server caches the fixed part of the prompt."""
    Warmer(llm, give_up_s=0).run()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--ws", default=WS_URL, help="brain WebSocket")
    p.add_argument("--llm", default=LLM_URL, help="llama-server base URL")
    p.add_argument("--bus", default=BUS, help="bus host:port (UDP)")
    p.add_argument("--once", metavar="KIND", choices=EVENT_KINDS,
                   help="print the narration for one fresh event of this kind and exit; nothing is sent")
    p.add_argument("--info", default="{}", help="event info for --once, as JSON")
    p.add_argument("--nodes", default=str(NODES_JSON), help="radio/nodes.json, for the zones")
    args = p.parse_args(argv)
    set_zones(load_zones(args.nodes))
    set_devices(load_devices(args.nodes))
    CROSSING_WIFI.clear()
    CROSSING_WIFI.update(load_crossing_wifi(args.nodes))
    llm = LlamaServer(args.llm)

    if args.once:
        narrator = Narrator(llm, send=lambda msg: None)
        event = {"v": 2, "type": "event", "t": narrator.clock(), "seq": 0, "src": "sim",
                 "id": "once", "kind": args.once, "info": json.loads(args.info)}
        print(json.dumps(narrator.narrate(event)), flush=True)
        return 0

    from narrator.recap import MAX_TOKENS, TIMEOUT_S, Recap   # here, because recap imports this module

    narrator = Narrator(llm, udp_sender(args.bus))
    narrator.warm = Warmer(LlamaServer(args.llm, timeout_s=WARM_TIMEOUT_S)).kick
    narrator.warm()
    recap = Recap(narrator, LlamaServer(args.llm, timeout_s=TIMEOUT_S, max_tokens=MAX_TOKENS))
    asyncio.run(serve(brain_messages(args.ws), narrator, recap=recap))
    return 0


if __name__ == "__main__":
    sys.exit(main())
