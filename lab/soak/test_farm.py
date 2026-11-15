"""Tests for the farm's own parts: the fault proxy's rules, the passers-by and the growth fit.

    python -m pytest lab/soak/test_farm.py
"""
import json
import random
import socket
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

import day  # noqa: E402
import proxy  # noqa: E402
import report  # noqa: E402


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_proxy_silences_a_receiver_and_a_beacon():
    p = proxy.Proxy(free_port(), ("127.0.0.1", 9), free_port())
    t = time.monotonic()
    p.quiet[("rx", "unoq")] = t + 10
    p.quiet[("tx", "west")] = t + 10
    assert p._silent({"link": "east>unoq:ble"}, t)
    assert p._silent({"link": "west>pi5:ble"}, t)
    assert not p._silent({"link": "east>pi5:ble"}, t)
    assert not p._silent({"link": ["not", "a", "string"]}, t)
    assert not p._silent({"link": "east>unoq:ble"}, t + 11)   # and it comes back


def test_proxy_drops_camera_and_counts():
    bus = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    bus.bind(("127.0.0.1", 0))
    bus.settimeout(2)
    listen, ctl = free_port(), free_port()
    p = proxy.Proxy(listen, bus.getsockname(), ctl)
    for target in (p.feed, p.delayed, p.control):
        threading.Thread(target=target, daemon=True).start()
    c = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    c.settimeout(2)
    c.sendto(json.dumps({"camera": False}).encode(), ("127.0.0.1", ctl))
    assert json.loads(c.recv(65535))["camera"] is False
    c.sendto(b'{"type": "label"}', ("127.0.0.1", listen))
    c.sendto(b'{"type": "rssi", "link": "east>pi5:ble", "dbm": -60}', ("127.0.0.1", listen))
    assert json.loads(bus.recv(65535))["type"] == "rssi"   # the label never arrives
    c.sendto(b"{}", ("127.0.0.1", ctl))
    counts = json.loads(c.recv(65535))
    assert counts["camera_dropped"] == 1 and counts["out"] == 1


def test_passers_drop_links_they_walk_near():
    from sim import fake
    events = [{"type": "rssi", "t": 1.0, "link": "east>pi5:ble", "kind": "ble", "tx": "east", "rx": "pi5", "dbm": -60}]
    pe = fake.NODES["pi5"]
    passer = {"t_on": 0.0, "t_off": 2.0, "x0": pe[0], "x1": pe[0], "y": pe[1], "in_frame": True}
    out = list(day.with_passers(iter(events), [passer], random.Random(1), fake))
    assert out[0]["dbm"] < -60
    label = {"type": "label", "t": 1.0, "persons_in_frame": 0}
    assert list(day.with_passers(iter([label]), [passer], random.Random(1), fake))[0]["persons_in_frame"] == 1


def test_slope_is_per_hour_and_needs_enough_points():
    pts = [(i * 600, 100 + i * 5) for i in range(8)]   # 5 per 10 minutes
    assert abs(report.slope(pts) - 30) < 1e-6
    assert report.slope(pts[:3]) is None
