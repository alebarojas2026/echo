"""Check the screen and data endpoints without sending board commands."""

import argparse
import asyncio
import json
from urllib.request import urlopen


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


async def websocket_check(url):
    from websockets.asyncio.client import connect

    async with asyncio.timeout(5):
        async with connect(url) as socket:
            async for message in socket:
                state = json.loads(message)
                if state.get("v") == 2 and state.get("type") == "state":
                    return
    raise ValueError("connection closed before receiving a state")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--http", default="http://192.168.77.2:8080")
    parser.add_argument("--ws", default="ws://192.168.77.2:8765/ws")
    args = parser.parse_args()
    base = args.http.rstrip("/")
    checks = [
        ("web", lambda: http_check(base + "/", screen)),
        ("nodes.json", lambda: http_check(base + "/nodes.json", fields("nodes", "links"))),
        ("proof.json", lambda: http_check(base + "/proof.json", fields("zone", "ms_per_decision", "watts"))),
        ("WebSocket", lambda: asyncio.run(websocket_check(args.ws))),
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
