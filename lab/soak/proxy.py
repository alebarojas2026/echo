"""Chaos proxy for the soak test (lab/soak/soak.py): sits between the sim feed and the bus.

    python lab/soak/proxy.py --listen 5610 --bus 127.0.0.1:5600 --control 5611

Every datagram from the sim is forwarded to the bus from one socket (so the bus
sees one producer). Faults, all switchable while it runs:
- drop:   lose a datagram with this probability;
- dup:    send a datagram twice with this probability;
- jitter: hold each datagram for a random 0..jitter_ms (so they can arrive out of order);
- silence(link, s): drop every reading of one link for s seconds;
- camera(False): drop the sim's cam and label messages and send cam "off" once a second
  from a second socket, the way teacher/camwatch.py reports an unplugged camera.
The soak sends JSON on the control port ({"packets": [drop, dup, jitter_ms]}, {"silence": [link, s]},
{"camera": false}) and gets the counts back. A pause of over 0.5 s in what the sim sends is printed,
so a stall in the test rig is never mistaken for one in the stack. Dev only.
"""
import argparse
import heapq
import itertools
import json
import random
import socket
import threading
import time


class ChaosProxy:
    def __init__(self, listen=("127.0.0.1", 5610), bus=("127.0.0.1", 5600), seed=0):
        self.rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rx.bind(listen)
        self.rx.settimeout(0.05)
        self.tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.cam_tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.bus, self.rand = bus, random.Random(seed)
        self.drop = self.dup = 0.0
        self.jitter_ms = 0
        self.silent = {}          # link -> monotonic time the silence ends
        self.camera_on = True
        self.counts = {"in": 0, "out": 0, "dropped": 0, "duplicated": 0, "silenced": 0, "cam_blocked": 0}
        self._held, self._n = [], itertools.count()
        self._cam_seq, self._next_cam = 0, 0.0
        self._lock, self._stop = threading.Lock(), threading.Event()
        self._last_in = None

    def set_packets(self, drop=0.0, dup=0.0, jitter_ms=0):
        self.drop, self.dup, self.jitter_ms = drop, dup, jitter_ms

    def silence(self, link, seconds):
        self.silent[link] = time.monotonic() + seconds

    def camera(self, on):
        self.camera_on = on
        self._next_cam = 0.0

    def _blocked(self, data):
        try:
            msg = json.loads(data)
        except ValueError:
            return None
        if not self.camera_on and msg.get("type") in ("cam", "label"):
            return "cam_blocked"
        until = self.silent.get(msg.get("link"))
        if until is not None and time.monotonic() < until:
            return "silenced"
        return None

    def _send(self, data, delay_s=0.0):
        if delay_s <= 0:
            self.tx.sendto(data, self.bus)
            self.counts["out"] += 1
            return
        with self._lock:
            heapq.heappush(self._held, (time.monotonic() + delay_s, next(self._n), data))

    def _flush(self):
        now = time.monotonic()
        with self._lock:
            due = []
            while self._held and self._held[0][0] <= now:
                due.append(heapq.heappop(self._held)[2])
        for data in due:
            self.tx.sendto(data, self.bus)
            self.counts["out"] += 1

    def _camwatch(self):
        now = time.monotonic()
        if self.camera_on or now < self._next_cam:
            return
        self._next_cam = now + 1.0
        self._cam_seq += 1
        msg = {"v": 2, "type": "cam", "t": int(time.time() * 1000), "seq": self._cam_seq, "src": "sim",
               "state": "off", "fps": 0.0}
        self.cam_tx.sendto(json.dumps(msg, separators=(",", ":")).encode(), self.bus)

    def handle(self, data):
        self.counts["in"] += 1
        now = time.monotonic()
        if self._last_in is not None and now - self._last_in > 0.5:
            print(json.dumps({"gap_s": round(now - self._last_in, 2), "t": round(time.time(), 3)}), flush=True)
        self._last_in = now
        why = self._blocked(data)
        if why:
            self.counts[why] += 1
            return
        if self.rand.random() < self.drop:
            self.counts["dropped"] += 1
            return
        copies = 2 if self.rand.random() < self.dup else 1
        self.counts["duplicated"] += copies - 1
        for _ in range(copies):
            self._send(data, self.rand.uniform(0, self.jitter_ms) / 1000 if self.jitter_ms else 0.0)

    def run(self):
        while not self._stop.is_set():
            try:
                self.handle(self.rx.recvfrom(65535)[0])
            except socket.timeout:
                pass
            except ConnectionResetError:
                pass   # Windows: an earlier send found the bus down
            try:
                self._flush()
                self._camwatch()
            except ConnectionResetError:
                pass

    def start(self):
        threading.Thread(target=self.run, daemon=True, name="proxy").start()
        return self

    def stop(self):
        self._stop.set()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--listen", type=int, default=5610)
    ap.add_argument("--bus", default="127.0.0.1:5600")
    ap.add_argument("--control", type=int, default=5611)
    a = ap.parse_args()
    host, port = a.bus.rsplit(":", 1)
    proxy = ChaosProxy(("127.0.0.1", a.listen), (host, int(port))).start()
    ctl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ctl.bind(("127.0.0.1", a.control))
    while True:
        data, addr = ctl.recvfrom(65535)
        cmd = json.loads(data)
        if "packets" in cmd:
            proxy.set_packets(*cmd["packets"])
        if "silence" in cmd:
            proxy.silence(*cmd["silence"])
        if "camera" in cmd:
            proxy.camera(cmd["camera"])
        ctl.sendto(json.dumps(proxy.counts).encode(), addr)


if __name__ == "__main__":
    main()
