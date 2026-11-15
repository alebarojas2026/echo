"""A UDP proxy between the sim feed and the bus that breaks the feed on command.

    python lab/soak/proxy.py --listen 5610 --bus 127.0.0.1:5600 --control 5611

Commands are JSON datagrams on the control port; every reply is the running counts.
    {"packets": [loss, dup, jitter_ms]}   drop, duplicate and delay messages (0 0 0 = clean)
    {"silence": [link, s]}                 one link sends nothing for s seconds
    {"rx_off": [node, s]}                  a receiver goes quiet: every link it hears, for s seconds
    {"tx_off": [node, s]}                  a beacon loses power: every link it sends, for s seconds
    {"camera": false|true}                 the camera unplugged: no cam or label messages get through
    {"garbage": n}                         n malformed datagrams straight to the bus
    {}                                     just the counts
Dev only: nothing in the demo goes through this.
"""
import argparse
import heapq
import json
import random
import socket
import threading
import time

GARBAGE = [
    b"", b"\x00\xff\xfe", b"not json", b"[1, 2, 3]", b"null", b'{"v": 2}', b'{"v": 2, "type": "rssi"}',
    b'{"v":2,"type":"rssi","t":1,"seq":1,"src":"live","link":"east>pi5:ble","kind":"ble","tx":"east","rx":"pi5","dbm":"loud"}',
    b'{"v":2,"type":"rssi","t":1,"seq":1,"src":"live","link":"east>pi5:ble","kind":"ble","tx":"east","rx":"pi5","dbm":NaN}',
    b'{"v":2,"type":"rssi","t":1,"seq":1,"src":"live","link":"east>pi5:ble","kind":"ble","tx":"east","rx":"pi5","dbm":Infinity}',
    b'{"v":2,"type":"rssi","t":1,"seq":1,"src":"live","link":"nowhere>pi5:ble","kind":"ble","tx":"nowhere","rx":"pi5","dbm":-60}',
    b'{"v":2,"type":"rssi","t":"soon","seq":"x","src":"live","link":["a"],"dbm":-60}',
    b'{"v":2,"type":"label","t":1,"seq":1,"src":"live","zone":"kitchen","present":"yes","persons_in_frame":-3,"foot_m":[1]}',
    b'{"v":2,"type":"cam","t":1,"seq":1,"src":"live","state":"exploded","fps":-1}',
    b'{"v":2,"type":"meta","t":1,"seq":1,"src":"live","session":"../../etc/x","purpose":"train"}',
    b'{"v":2,"type":"narration","t":1,"seq":1,"src":"live","text":null,"event_id":5}',
    b'{"v":2,"type":"cmd","cmd":"reset","args":{}}',
    b'{"v":2,"type":"rssi","t":1,"seq":1,"src":"live","link":"east>pi5:ble","dbm":-60,"recv_t":"x"}',
    b'{"v":3,"type":"rssi"}', b'{"type": {"a": 1}}', b"9" * 4000, b'{"a":' * 500,
]


class Proxy:
    def __init__(self, listen, bus, control, seed=0):
        self.inp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.inp.bind(("127.0.0.1", listen))
        self.ctl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.ctl.bind(("127.0.0.1", control))
        self.out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)   # one socket: one producer for the bus
        self.bus = bus
        self.rng = random.Random(seed)
        self.loss = self.dup = self.jitter_ms = 0.0
        self.quiet = {}           # ("link"|"rx"|"tx", name) -> until (monotonic)
        self.camera = True
        self.counts = {"in": 0, "out": 0, "dropped": 0, "duplicated": 0, "silenced": 0, "camera_dropped": 0,
                       "garbage": 0, "ctl": 0}
        self.heap, self.n, self.cv = [], 0, threading.Condition()

    def _silent(self, msg, now):
        link = msg.get("link")
        if not isinstance(link, str):
            return False
        tx, _, rest = link.partition(">")
        rx = rest.split(":")[0]
        for key in (("link", link), ("rx", rx), ("tx", tx)):
            until = self.quiet.get(key)
            if until is not None:
                if now < until:
                    return True
                del self.quiet[key]
        return False

    def feed(self):
        while True:
            data, _ = self.inp.recvfrom(65535)
            self.counts["in"] += 1
            try:
                msg = json.loads(data)
            except ValueError:
                msg = {}
            now = time.monotonic()
            kind = msg.get("type") if isinstance(msg, dict) else None
            if kind in ("cam", "label") and not self.camera:
                self.counts["camera_dropped"] += 1
                continue
            if kind == "rssi" and self._silent(msg, now):
                self.counts["silenced"] += 1
                continue
            if kind == "rssi" and self.loss and self.rng.random() < self.loss:
                self.counts["dropped"] += 1
                continue
            copies = 2 if self.dup and self.rng.random() < self.dup else 1
            self.counts["duplicated"] += copies - 1
            for _ in range(copies):
                delay = self.rng.uniform(0, self.jitter_ms) / 1000 if self.jitter_ms else 0.0
                if delay <= 0:
                    self._send(data)
                else:
                    with self.cv:
                        self.n += 1
                        heapq.heappush(self.heap, (now + delay, self.n, data))
                        self.cv.notify()

    def _send(self, data):
        try:
            self.out.sendto(data, self.bus)
            self.counts["out"] += 1
        except OSError:
            pass

    def delayed(self):
        while True:
            with self.cv:
                while not self.heap:
                    self.cv.wait()
                due, _, data = self.heap[0]
                wait = due - time.monotonic()
                if wait > 0:
                    self.cv.wait(wait)
                    continue
                heapq.heappop(self.heap)
            self._send(data)

    def control(self):
        while True:
            data, addr = self.ctl.recvfrom(65535)
            self.counts["ctl"] += 1
            try:
                cmd = json.loads(data)
            except ValueError:
                cmd = {}
            now = time.monotonic()
            if "packets" in cmd:
                self.loss, self.dup, self.jitter_ms = (float(x) for x in cmd["packets"])
            for key, what in (("silence", "link"), ("rx_off", "rx"), ("tx_off", "tx")):
                if key in cmd:
                    name, secs = cmd[key]
                    self.quiet[(what, name)] = now + float(secs)
            if "camera" in cmd:
                self.camera = bool(cmd["camera"])
            for _ in range(int(cmd.get("garbage", 0))):
                self._send(self.rng.choice(GARBAGE))
                self.counts["garbage"] += 1
            reply = dict(self.counts, loss=self.loss, camera=self.camera, delayed=len(self.heap))
            self.ctl.sendto(json.dumps(reply).encode(), addr)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--listen", type=int, default=5610)
    ap.add_argument("--bus", default="127.0.0.1:5600")
    ap.add_argument("--control", type=int, default=5611)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    host, port = a.bus.rsplit(":", 1)
    p = Proxy(a.listen, (host, int(port)), a.control, a.seed)
    for target in (p.delayed, p.control):
        threading.Thread(target=target, daemon=True).start()
    p.feed()


if __name__ == "__main__":
    main()
