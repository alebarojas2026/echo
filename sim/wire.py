"""The one place that knows what a message looks like on the wire.

Speaks CONTRACTS.md v2, sections 1 and 4. If the contract changes, change
this file and nothing else.

Internal events already use the contract's field names; they only lack the
envelope and carry `t` in seconds since the start of the run:
    {"type": "rssi", "t": 1.2, "link": "east>pi5:ble", "kind": "ble",
     "tx": "east", "rx": "pi5", "dbm": -61}
"""
import itertools
import json

VERSION = 2


def _dump(msg: dict) -> str:
    return json.dumps(msg, separators=(",", ":"))


def encoder(start_ms: int = 0, src: str = "sim"):
    """Return encode(event) -> one JSON line. One encoder = one producer (one seq counter)."""
    seq = itertools.count(1)

    def encode(event: dict) -> str:
        msg = {"v": VERSION, "type": event["type"],
               "t": start_ms + round(event["t"] * 1000), "seq": next(seq), "src": src}
        msg.update((k, v) for k, v in event.items() if k not in ("type", "t"))
        return _dump(msg)

    return encode


def time_of(line: str) -> float:
    """Seconds, for pacing a replay. Uses the bus's recv_t when the line has one."""
    msg = json.loads(line)
    return msg.get("recv_t", msg["t"]) / 1000.0


def as_replay(line: str, seq: int | None = None) -> str:
    """Mark a recorded line as replayed; the bus stamps a fresh recv_t.

    A recording interleaves several producers, each with its own seq. When it is
    sent again from one socket, pass a fresh `seq` so the bus sees one producer.
    """
    msg = json.loads(line)
    msg["src"] = "replay"
    if seq is not None:
        msg["seq"] = seq
    msg.pop("recv_t", None)
    return _dump(msg)
