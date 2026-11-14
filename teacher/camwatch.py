"""Host service: camera presence, processed-frame freshness and App Lab lifecycle."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import os
from pathlib import Path
import socket
import subprocess
import time


class Watcher:
    def __init__(self, send, action, stall_ms=1000):
        self.send, self.action = send, action
        self.stall_ms = stall_ms
        self.present = None
        self.connected_at = None
        self.started = False
        self.last_emit = None
        self.state = None
        self.seq = 0
        self.previous_heartbeat = None
        self.fps = 0.0

    def tick(self, now, present, heartbeat=None):
        if present != self.present:
            self.present = present
            self.connected_at = now if present else None
            self.started = False
            self.previous_heartbeat = None
            self.fps = 0.0
            if not present:
                self.action("stop")
        if present and not self.started and now - self.connected_at >= 2000:
            self.action("start")
            self.started = True
        fresh = False
        if present and isinstance(heartbeat, dict):
            t, frame = heartbeat.get("t"), heartbeat.get("frame")
            fresh = (isinstance(t, (int, float)) and isinstance(frame, int)
                     and frame > 0 and self.connected_at <= t <= now
                     and now - t < self.stall_ms)
            if fresh:
                old = self.previous_heartbeat
                if old and t > old["t"] and frame > old["frame"]:
                    self.fps = 1000 * (frame - old["frame"]) / (t - old["t"])
                self.previous_heartbeat = heartbeat
        state = "off" if not present else "on" if fresh else "stalled"
        if not fresh:
            self.fps = 0.0
        if state != self.state or self.last_emit is None or now - self.last_emit >= 1000:
            self.seq += 1
            message = dict(v=2, type="cam", t=now, seq=self.seq, src="live", state=state, fps=self.fps)
            self.send(message)
            self.last_emit = now
            self.state = state
            return message


def read_heartbeat(path):
    try:
        value = path.read_text()
        return json.loads(value)
    except (OSError, ValueError):
        return None


def discover_device(override=None, directory=Path("/dev/v4l/by-id")):
    """Resolve USB capture index 0 anew on every poll, including after replug."""
    if override is not None:
        return Path(override)
    return next((path for path in sorted(directory.glob("usb-*-video-index0")) if path.exists()), None)


def run_action(app, action):
    # Keep lifecycle work off the polling thread so off/stalled heartbeats continue.
    for attempt in range(3):
        try:
            subprocess.run(["arduino-app-cli", "app", action, app], check=True, timeout=30,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            return
        except (OSError, subprocess.SubprocessError):
            logging.exception("teacher app %s failed (attempt %s)", action, attempt + 1)
            time.sleep(1)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", type=Path, default=os.environ.get("TEACHER_DEVICE"))
    parser.add_argument("--heartbeat", type=Path, default=os.environ.get("TEACHER_HEARTBEAT"))
    parser.add_argument("--app", default=os.environ.get("TEACHER_APP"), help="App Lab app path or user: alias")
    args = parser.parse_args(argv)
    if args.heartbeat is None or not args.app or not args.app.strip():
        parser.error("set TEACHER_HEARTBEAT and TEACHER_APP in .env, or pass --heartbeat and --app")
    logging.basicConfig(level=logging.INFO)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp, ThreadPoolExecutor(max_workers=1) as worker:
        def send(message):
            udp.sendto(json.dumps(message, allow_nan=False).encode(), ("127.0.0.1", 5600))

        watcher = Watcher(send, lambda action: worker.submit(run_action, args.app, action))
        while True:
            device = discover_device(args.device)
            watcher.tick(int(time.time() * 1000), device is not None and device.exists(), read_heartbeat(args.heartbeat))
            time.sleep(0.05)


if __name__ == "__main__":
    main()
