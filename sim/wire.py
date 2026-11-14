"""The one place that knows what a message looks like on the wire.

The shared contract (CONTRACTS.md) is not frozen yet. When it lands, change
`encode` (and `time_of` if the timestamp field moves) and nothing else.

Internal events are plain dicts:
    {"kind": "rssi",  "t": 1.2, "link": "n0-n1", "rssi": -47}
    {"kind": "label", "t": 1.2, "zone": 3, "present": True, "moving": False}
"""
import json


def encode(event: dict) -> str:
    """Internal event -> one JSON line (no trailing newline)."""
    msg = {"type": event["kind"]}
    msg.update((k, v) for k, v in event.items() if k != "kind")
    return json.dumps(msg, separators=(",", ":"))


def time_of(line: str) -> float:
    """Timestamp in seconds of one JSON line. Used by replay for pacing."""
    return float(json.loads(line)["t"])
