"""The go / no-go before a judge: is the board serving, sensing, trained, on time and keeping records?

It reads only. Nothing here sends a board command; the one POST is a question to /ask.
Each line is PASS, WARN or FAIL, and a FAIL says what to do. Exit code 1 on any FAIL.
"""

import argparse
import asyncio
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

CLOCK_LIMIT_S = 60       # the board's clock against this machine's
RECORD_SPAN_MS = 60_000  # the stretch of records asked for
RECORD_ROWS = 30         # one row a second is saved; half of them missing is a store in trouble
QUESTION = "Is anyone here right now?"


class Warn(Exception):
    """Worth reading, but not a reason to stop."""


def http_check(url, validate):
    with urlopen(url, timeout=5) as response:
        validate(response.read())


def screen(body):
    if b"<html" not in body.lower():
        raise ValueError("expected an HTML screen")


def fields(*keys):
    def validate(body):
        value = json.loads(body)
        if not isinstance(value, dict) or not all(key in value for key in keys):
            raise ValueError("required fields missing")
    return validate


def configured_layout():
    path = Path(__file__).resolve().parents[1] / "radio" / "nodes.json"
    return json.loads(path.read_text(encoding="utf-8-sig"))


def layout_counts(body):
    value = json.loads(body)
    expected = configured_layout()
    for key in ("nodes", "links"):
        if not isinstance(value.get(key), list) or len(value[key]) != len(expected[key]):
            raise ValueError(f"{key} count differs from the configured layout")


async def websocket_check(url):
    from websockets.asyncio.client import connect

    async with asyncio.timeout(5):
        async with connect(url) as socket:
            async for message in socket:
                state = json.loads(message)
                if state.get("v") == 2 and state.get("type") == "state":
                    return state
    raise ValueError("connection closed before receiving a state")


def need_state(state):
    if state is None:
        raise ValueError("no state to read (see WebSocket)")
    return state


def health_check(state):
    health = need_state(state).get("health") or {}
    status = health.get("status")
    if status == "ok":
        return
    quiet = [link.get("id") for link in state.get("links") or [] if link.get("status") != "ok"]
    named = ", ".join(str(link) for link in (health.get("blind") or quiet)) or "no link named"
    if status == "degraded":
        # A slow link reads stale now and then on the real kit; the board still predicts. Blind is the stop.
        raise Warn(f"health is degraded ({named}): the board still predicts; check that device if it stays")
    raise ValueError(f"health is {status or 'missing'} ({named}): check that device's power and its place, then wait 3 s")


def links_check(state, layout=None):
    heard = {link.get("id") for link in need_state(state).get("links") or [] if (link.get("rate_hz") or 0) > 0}
    missing = [link["id"] for link in (layout or configured_layout())["links"] if link["id"] not in heard]
    if missing:
        raise ValueError(f"no readings on {', '.join(missing)}: check the sender is powered and joined")


def model_check(state, before_lesson=False):
    if (need_state(state).get("model") or {}).get("trained") is True:
        return
    if before_lesson:
        raise Warn("not trained yet: run the lesson before the first judge")
    raise ValueError("the model is not trained: take the baseline, then run the lesson")


def clock_check(state, now_ms=None):
    t = need_state(state).get("t")
    if not isinstance(t, (int, float)):
        raise ValueError("the state has no time")
    off_s = (t - (time.time() * 1000 if now_ms is None else now_ms)) / 1000
    if abs(off_s) > CLOCK_LIMIT_S:
        way = "ahead of" if off_s > 0 else "behind"
        raise ValueError(f"the board's clock is {abs(off_s):.0f} s {way} this machine: set the board's clock, then restart the units")


def get_json(url, data=None, timeout=5):
    request = Request(url, data=None if data is None else json.dumps(data).encode(),
                      headers={"Content-Type": "application/json"} if data is not None else {})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def records_check(base, state):
    # The span is in the board's own time, so a clock that is off fails its own check, not this one.
    to_t = int(need_state(state)["t"])
    try:
        history = get_json(f"{base}/history?from_t={to_t - RECORD_SPAN_MS}&to_t={to_t}")
    except HTTPError as error:
        if error.code == 404:
            raise ValueError("/history is not served: the web server has no records mounted") from None
        raise
    rows = history.get("rows") if isinstance(history, dict) else None
    count = len(rows) if isinstance(rows, list) else 0
    if count < RECORD_ROWS:
        raise ValueError(f"{count} records in the last minute (expected about 60): is the store running?")


def ask_check(base, timeout=20):
    try:
        reply = get_json(base + "/ask", {"question": QUESTION}, timeout)
    except HTTPError as error:
        why = {404: "/ask is not served", 503: "ask is not set up on the web server (store or model missing)",
               500: "the room could not answer: check the store and llama-server"}.get(error.code)
        raise ValueError(why or f"/ask answered {error.code}") from None
    if not isinstance(reply, dict) or not str(reply.get("answer") or "").strip():
        raise ValueError("/ask gave no answer")
    if reply.get("picked_by") != "llm":
        raise Warn(f"answered, picked by {reply.get('picked_by') or 'unknown'}: the on-board model did not pick the tool")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--http", default="http://192.168.77.2:8080")
    parser.add_argument("--ws", default="ws://192.168.77.2:8765/ws")
    parser.add_argument("--before-lesson", action="store_true", help="a model that is not trained yet is a warning")
    parser.add_argument("--no-ask", action="store_true", help="skip the question to /ask (it takes seconds)")
    args = parser.parse_args(argv)
    base = args.http.rstrip("/")
    seen = {}

    def websocket():
        seen["state"] = asyncio.run(websocket_check(args.ws))

    state = lambda: seen.get("state")   # noqa: E731
    checks = [
        ("web", lambda: http_check(base + "/", screen)),
        ("nodes.json", lambda: http_check(base + "/nodes.json", layout_counts)),
        ("proof.json", lambda: http_check(base + "/proof.json", fields("zone", "ms_per_decision", "watts"))),
        ("WebSocket", websocket),
        ("health", lambda: health_check(state())),
        ("links", lambda: links_check(state())),
        ("model", lambda: model_check(state(), args.before_lesson)),
        ("board clock", lambda: clock_check(state())),
        ("records", lambda: records_check(base, state())),
    ]
    if not args.no_ask:
        checks.append(("ask", lambda: ask_check(base)))
    failed = passed = 0
    for name, check in checks:
        try:
            check()
        except Warn as warning:
            print(f"WARN {name}: {warning}")
            passed += 1
        except Exception as error:
            print(f"FAIL {name}: {str(error) or type(error).__name__}")
            failed += 1
        else:
            print(f"PASS {name}")
            passed += 1
    print(f"{passed} of {len(checks)} pass" + ("" if failed else ": go"))
    return int(failed > 0)


if __name__ == "__main__":
    raise SystemExit(main())
