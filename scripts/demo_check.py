"""Check the screen and data endpoints without sending board commands.

records and ask fail unless the board is keeping records: GET /history for the board's last
minute (its own clock, from the state) must have rows, and POST /ask must answer.
"""

import argparse
import asyncio
import json
from pathlib import Path
from urllib.request import Request, urlopen

ASK = "Is anyone here?"


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


def layout_counts(body):
    value = json.loads(body)
    expected = json.loads((Path(__file__).resolve().parents[1] / "radio" / "nodes.json").read_text(encoding="utf-8-sig"))
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
                    return state.get("t")
    raise ValueError("connection closed before receiving a state")


def records_check(base, board_t):
    if not isinstance(board_t, int):
        raise ValueError("no board time: the WebSocket check has to pass first")
    with urlopen(f"{base}/history?from_t={board_t - 60_000}&to_t={board_t}", timeout=10) as response:
        rows = json.loads(response.read()).get("rows")
    if not rows:
        raise ValueError("no records in the board's last minute; is radio-sight-store running?")


def ask_check(base):
    request = Request(base + "/ask", data=json.dumps({"question": ASK}).encode(),
                      headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=90) as response:
        answer = json.loads(response.read()).get("answer")
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("/ask gave no answer")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--http", default="http://192.168.77.2:8080")
    parser.add_argument("--ws", default="ws://192.168.77.2:8765/ws")
    args = parser.parse_args()
    base = args.http.rstrip("/")
    board = {}
    checks = [
        ("web", lambda: http_check(base + "/", screen)),
        ("nodes.json", lambda: http_check(base + "/nodes.json", layout_counts)),
        ("proof.json", lambda: http_check(base + "/proof.json", fields("zone", "ms_per_decision", "watts"))),
        ("WebSocket", lambda: board.update(t=asyncio.run(websocket_check(args.ws)))),
        ("records", lambda: records_check(base, board.get("t"))),
        ("ask", lambda: ask_check(base)),
    ]
    failed = False
    for name, check in checks:
        try:
            check()
        except Exception as error:
            print(f"FAIL {name}: {str(error) or type(error).__name__}")
            failed = True
        else:
            print(f"PASS {name}")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
