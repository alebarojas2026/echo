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

WS_URL = "ws://127.0.0.1:8765/ws"
LLM_URL = "http://127.0.0.1:8091"
BUS = "127.0.0.1:5600"

GAP_MS = 8000         # at most one sentence every 8 s
MAX_AGE_MS = 3000     # only for events up to 3 s old
LLM_TIMEOUT_S = 8.0   # slower than this -> template
MAX_WORDS = 16

EVENT_KINDS = ("enter", "exit", "zone_change", "checkin", "object_on", "object_off", "advice",
               "advice_result", "router_moved", "router_home", "recalibrating", "cam_off", "cam_on",
               "cam_stalled", "alert_on", "alert_off", "blind_on", "blind_off", "trained",
               "baseline_done", "drift")
# Which waiting event to keep, most important first. Kinds not listed rank below all of these.
PRIORITY = ("alert_on", "checkin", "cam_off", "advice_result", "object_on", "blind_on", "enter",
            "recalibrating", "trained", "zone_change", "exit")
NEVER = ("router_moved", "advice")   # the screen already says these itself
ZONES = {1: ("Bed", 60), 2: ("Chair", None), 3: ("Hall", None), 4: ("Bathroom", 10)}  # name, still_alert_s
NODES = {"unoq": "receiver", "pi5": "router", "east": "east beacon", "west": "west beacon"}

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

def _zone(z) -> str | None:
    return f"zone {z} ({ZONES[z][0]})" if z in ZONES else None


def _link(link) -> str | None:
    m = re.fullmatch(r"(\w+)>(\w+):\w+", str(link or ""))
    return f"{NODES.get(m[1], m[1])} to {NODES.get(m[2], m[2])}" if m else None


def _dbm(v) -> int | None:
    return round(v) if isinstance(v, (int, float)) else None


def template(kind: str, info: dict) -> str | None:
    """The fixed sentence for an event, or None for a kind we don't know."""
    zone = _zone(info.get("zone"))
    near = f" near the {NODES[info['node']]}" if info.get("node") in NODES else ""
    link = _link(info.get("link"))
    before, after = _dbm(info.get("before_dbm")), _dbm(info.get("after_dbm"))
    limit = info.get("limit_s") or ZONES.get(info.get("zone"), (None, None))[1]
    sentences = {
        "enter": f"Someone just walked into {zone or 'the room'}.",
        "exit": f"Someone just left the room from {zone}." if zone else "Someone just left the room.",
        "zone_change": f"Someone moved to {zone or 'another zone'}.",
        "checkin": f"Check-in received from {zone}." if zone else "Check-in received on the router link.",
        "object_on": f"A new object{near or ' in the room'} is weakening the signal.",
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

SYSTEM = (
    "You write captions for the screen of a Wi-Fi sensing demo. The room has four zones: "
    "zone 1 (Bed), zone 2 (Chair), zone 3 (Hall) and zone 4 (Bathroom). "
    "Rewrite the facts as one short, friendly sentence of at most 12 words. "
    "Use only the facts given. Call a person someone. Say no movement when nobody moves. "
    "Reply with the sentence only."
)
EXAMPLES = (
    ("enter", "Someone just walked into zone 2 (Chair).",
     "Someone just stepped into zone 2, by the chair."),
    ("advice_result", "After the move, the router's Wi-Fi went from -71 to -63 dBm.",
     "Moving the router lifted its Wi-Fi from -71 to -63 dBm."),
)


def prompt(kind: str, facts: str) -> list[dict]:
    """Chat messages for one event. Everything before the last message never changes,
    so llama-server keeps it cached and only the event itself is new work."""
    msgs = [{"role": "system", "content": SYSTEM}]
    for k, f, s in EXAMPLES:
        msgs.append({"role": "user", "content": f"Event: {k}. Facts: {f}"})
        msgs.append({"role": "assistant", "content": s})
    msgs.append({"role": "user", "content": f"Event: {kind}. Facts: {facts}"})
    return msgs


class LlamaServer:
    """llama-server's OpenAI-style chat endpoint. Call it with chat messages;
    it returns (text, model name). A reply cut off by max_tokens comes back empty."""

    def __init__(self, url: str = LLM_URL, timeout_s: float = LLM_TIMEOUT_S):
        self.url = url.rstrip("/") + "/v1/chat/completions"
        self.timeout_s = timeout_s

    def __call__(self, messages: list[dict]) -> tuple[str, str | None]:
        body = {"messages": messages, "max_tokens": 40, "temperature": 0.2,
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
    try:
        return POOL.submit(fn, *args).result(timeout=timeout_s)
    except concurrent.futures.TimeoutError:
        raise TimeoutError(f"no reply in {timeout_s:g} s") from None


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
    return None


# ---------------------------------------------------------------- narrator

class Narrator:
    """Picks which events to narrate and builds the narration messages.

    llm(messages) -> (text, model) and send(msg) are injected, so tests can
    use fakes. clock() returns epoch ms.
    """

    def __init__(self, llm, send, clock=now_ms, timeout_s=LLM_TIMEOUT_S,
                 gap_ms=GAP_MS, max_age_ms=MAX_AGE_MS, sleep=time.sleep):
        self.llm, self.send, self.clock, self.sleep = llm, send, clock, sleep
        self.timeout_s, self.gap_ms, self.max_age_ms = timeout_s, gap_ms, max_age_ms
        self.pending = None       # the most important event not yet narrated
        self.cam = None           # on | off | stalled, from the brain
        self.seq = 0
        self.last_start_ms = None   # when the last sentence started being written
        self.last_sent_ms = None

    def observe(self, msg: dict) -> None:
        """Take any message from the brain."""
        if msg.get("type") == "state" and "cam" in msg:
            self.cam = msg["cam"]
        elif msg.get("type") == "event" and msg.get("kind") in EVENT_KINDS:
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

    def _fresh(self, event: dict, now) -> bool:
        t = event.get("t")
        return isinstance(t, (int, float)) and isinstance(now, (int, float)) and now - t <= self.max_age_ms

    def due(self, now: int) -> dict | None:
        """The pending event if it may be narrated now. Drops it once it is too old."""
        event = self.pending
        if event is None:
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
        try:
            raw, model = within(self.timeout_s, self.llm, prompt(event["kind"], facts))
        except TimeoutError:
            return facts, "template", None, "model too slow"
        except Exception as e:
            return facts, "template", None, f"model unreachable ({e})"
        text = clean(raw)
        why = problem(text, facts, self.cam == "off")
        if why:
            return facts, "template", None, f"{why}: {raw.strip()!r}"
        return text, "llm", model, "ok"

    def narrate(self, event: dict) -> dict:
        """Build, send and return the narration for one event."""
        start = self.clock()
        text, source, model, why = self.sentence(event)
        gen_ms = self.clock() - start
        if self.last_sent_ms is not None:   # a quick sentence after a slow one waits its turn:
            wait_ms = self.last_sent_ms + self.gap_ms - self.clock()   # the screen gets one per 8 s
            if wait_ms > 0:
                self.sleep(wait_ms / 1000)
        t = self.clock()
        self.seq += 1
        msg = {"v": 2, "type": "narration", "t": t, "seq": self.seq, "src": event.get("src", "live"),
               "text": text, "event_id": event.get("id"), "event_kind": event["kind"],
               "gen_ms": gen_ms, "source": source, "model": model}
        self.send(msg)
        self.last_sent_ms = t
        log(f"{event.get('id')} {event['kind']} -> {source} {gen_ms} ms ({why}): {text}")
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


async def serve(messages, narrator: Narrator, poll_s: float = 0.1) -> None:
    """Feed brain messages to the narrator and narrate whenever an event is due.
    Returns once the messages end and nothing is left to narrate."""
    async def feed():
        async for msg in messages:
            narrator.observe(msg)

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
    try:
        llm(prompt("enter", template("enter", {"zone": 2})))
    except Exception as e:
        log("warm-up failed:", e)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--ws", default=WS_URL, help="brain WebSocket")
    p.add_argument("--llm", default=LLM_URL, help="llama-server base URL")
    p.add_argument("--bus", default=BUS, help="bus host:port (UDP)")
    p.add_argument("--once", metavar="KIND", choices=EVENT_KINDS,
                   help="print the narration for one fresh event of this kind and exit; nothing is sent")
    p.add_argument("--info", default="{}", help="event info for --once, as JSON")
    args = p.parse_args(argv)
    llm = LlamaServer(args.llm)

    if args.once:
        narrator = Narrator(llm, send=lambda msg: None)
        event = {"v": 2, "type": "event", "t": narrator.clock(), "seq": 0, "src": "sim",
                 "id": "once", "kind": args.once, "info": json.loads(args.info)}
        print(json.dumps(narrator.narrate(event)), flush=True)
        return 0

    threading.Thread(target=warm_up, args=(llm,), daemon=True).start()
    asyncio.run(serve(brain_messages(args.ws), Narrator(llm, udp_sender(args.bus))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
