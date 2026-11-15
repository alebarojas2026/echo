"""Run one live lesson from a terminal and time it; commands and numbers only, never frames.

    python -m proof.lesson lesson-01 w1            # on the laptop or the board, the brain running

It sends what the screen will send (CONTRACTS.md section 5: label_mode person, record_start with
purpose train, then train while the recording is still open), tells the person what to do, and
prints what the brain says back once a second. The lesson starts with the space empty and has one
step out of view in the middle (teacher/lesson.py says why): train is not sent until the camera
has seen nobody for a few seconds, so a lesson with no empty time is never finished.

    12 s  camera: zone 1   radio: zone 1   learning: 6 of 10   fits: 1

and, once each: how long after the start the first model was there, how long until the radio first
gave the camera's answer, and the agreement REPORT_S after the start. Unplug the camera whenever
you like: it keeps printing what the radio says. Ctrl-C stops the recording and ends it.

    python -m proof.lesson empty-01 none --no-train            # record without a lesson (the empty space)
    python -m proof.lesson box-06 w1 --no-train --purpose demo # only look at what the camera says
    python -m proof.lesson --labels data/sessions/box-06.jsonl # count the labels in a recording
"""
import argparse
import json
import re
from pathlib import Path
from contextlib import nullcontext
import time

from teacher.lesson import NO_EMPTY, EmptyTime, script

TEACH_S = 30      # empty time and occupied steps before the first fit
STEP_S = 4        # seconds per occupied step
REPORT_S = 40     # when the agreement is read off (10 s after train, as before)


class Coach:
    """Feed it every message from the brain's WebSocket; it sends the commands and says what it sees."""

    def __init__(self, session, walker, send, say=print, teach_s=TEACH_S, step_s=STEP_S, report_s=REPORT_S,
                 purpose="train", train=True):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", session):
            raise ValueError("session must be a unique simple id, at most 64 characters")
        if not walker.strip():
            raise ValueError("walker id is required; use a pseudonym")
        self.session, self.walker, self.send_raw, self.say = session, walker, send, say
        self.teach_s, self.step_s, self.report_s = (teach_s if train else float("inf")), step_s, report_s
        self.purpose, self.train = purpose, train
        self.t0 = self.model_s = self.follows_s = self.report = None
        self.said_s = self.side = 0
        self.trained_sent = self.cam_off_said = self.no_empty_said = False
        self.steps = script(teach_s, step_s) if train else []
        self.empty = EmptyTime()

    def cmd(self, name, **args):
        self.send_raw({"v": 2, "type": "cmd", "cmd": name, "args": args})

    def start(self):
        self.cmd("label_mode", mode="person")
        self.cmd("record_start", session=self.session, purpose=self.purpose, walker=self.walker)

    def stop(self):
        self.cmd("record_stop")
        self.cmd("label_mode", mode="off")
        self.say(self.summary())

    def on_message(self, msg):
        if msg.get("type") == "event" and msg.get("kind") == "trained" and self.t0 is not None \
                and self.model_s is None and self.trained_sent:
            self.model_s = round((msg["t"] - self.t0) / 1000, 1)
            self.say(f"first model {self.model_s} s after the start")
        if msg.get("type") != "state":
            return
        if self.t0 is None:
            self.t0 = msg["t"]
        s = (msg["t"] - self.t0) / 1000
        pred, teacher = msg.get("pred"), msg.get("teacher")
        self.empty.saw(s, msg.get("cam"), teacher)
        while self.side < len(self.steps) and s >= self.steps[self.side][0]:
            self.say("\n" + self.steps[self.side][2])
            self.side += 1
        if s >= self.teach_s and not self.trained_sent:
            if self.empty.ok():
                self.trained_sent = True
                self.cmd("train")
                self.say("\ntrain sent. Keep entering and leaving the sensing area; unplug the camera when you like.")
            elif not self.no_empty_said:
                self.no_empty_said = True
                self.say("\n" + NO_EMPTY)
        training = (msg.get("model") or {}).get("training") or {}
        lesson = training.get("lesson")
        if self.follows_s is None and pred and teacher and teacher["present"] and pred["present"] \
                and pred["zone"] == teacher["zone"]:
            self.follows_s = round(s, 1)
            self.say(f"the radio first gave the camera's zone {self.follows_s} s after the start")
        if self.train and self.report is None and s >= self.report_s:
            self.report = (lesson["agree"], lesson["of"], lesson["fits"]) if lesson else ()
            self.say(f"{self.report_s} s after the start: " + self.agreement())
        if msg.get("cam") == "off" and self.trained_sent and not self.cam_off_said:
            self.cam_off_said = True
            self.say("\nthe camera is off. The radio carries on:")
        if int(s) != self.said_s:
            self.said_s = int(s)
            self.say(f"{int(s):3d} s  camera: {_zone(teacher, msg.get('cam'))}   radio: {_zone(pred)}   "
                     + (f"learning: {lesson['agree']} of {lesson['of']}   fits: {lesson['fits']}" if lesson else ""))

    def agreement(self):
        if self.report is None:
            return "not reached"
        if not self.report:
            return "no lesson was running"
        return f"the radio agreed with the camera on {self.report[0]} of the last {self.report[1]} decisions ({self.report[2]} fits)"

    def summary(self):
        if not self.train:
            return f"\nrecorded {self.session} ({self.purpose}); no lesson was asked for"
        unknown = "never"
        return (f"\nfirst model: {self.model_s if self.model_s is not None else unknown} s after the start\n"
                f"radio first right: {self.follows_s if self.follows_s is not None else unknown} s after the start\n"
                f"at {self.report_s} s: {self.agreement()}\n" + self.empty.summary())


def _zone(block, cam="on"):
    if cam != "on":
        return "off     "
    if not block:
        return "--      "
    return f"zone {block['zone']}  " if block["present"] else "nobody  "


def label_summary(lines) -> str:
    """What the camera said during a recording: how many labels, and how many of each kind."""
    labels = []
    for line in lines:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if isinstance(msg, dict) and msg.get("type") == "label":
            labels.append(msg)
    if not labels:
        return "no camera labels in this recording"
    times = [m.get("recv_t", m["t"]) for m in labels]
    span = max((times[-1] - times[0]) / 1000, 0.001)
    count = lambda test: sum(1 for m in labels if test(m))   # noqa: E731
    zones = sorted({m["zone"] for m in labels if m["zone"]})
    return (f"{len(labels)} labels in {span:.1f} s ({(len(labels) - 1) / span:.1f} a second)\n"
            f"nobody in frame: {count(lambda m: m['persons_in_frame'] == 0)}\n"
            f"one person, usable: {count(lambda m: m['persons_in_frame'] == 1 and not m['clipped'])}"
            + "".join(f"   zone {z}: {count(lambda m: m['zone'] == z)}" for z in zones) + "\n"
            f"one person, dropped (dead band or side edge): {count(lambda m: m['persons_in_frame'] == 1 and m['clipped'])}\n"
            f"more than one person: {count(lambda m: m['persons_in_frame'] > 1)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("session", nargs="?", help="a new session id")
    parser.add_argument("walker", nargs="?", help="pseudonymous walker id")
    parser.add_argument("--purpose", default="train", choices=["train", "demo"], help="demo = never used for training")
    parser.add_argument("--no-train", action="store_true", help="only record: no train, so no lesson")
    parser.add_argument("--labels", type=Path, help="count the camera labels in a recorded session file and stop")
    parser.add_argument("--url", default="ws://192.168.77.2:8765/ws")
    parser.add_argument("--teach-s", type=float, default=TEACH_S, help="seconds of stepping before the first fit")
    parser.add_argument("--capture", type=Path, help="exclusive numeric state/event capture, on the board only")
    args = parser.parse_args()
    if args.labels:
        print(label_summary(args.labels.read_text(encoding="utf-8").splitlines()))
        return
    if not (args.session and args.walker):
        parser.error("a session id and a walker id are needed")
    recorded = Path(__file__).resolve().parents[1] / "data/sessions" / (args.session + ".jsonl")
    if recorded.exists():
        parser.error("session already exists; use a new id")
    if args.capture:
        from proof.provenance import require_board
        require_board()
    from websockets.sync.client import connect
    with (args.capture.open("x",encoding="utf-8") if args.capture else nullcontext()) as output, connect(args.url) as ws:
        coach = Coach(args.session, args.walker, lambda msg: ws.send(json.dumps(msg)), teach_s=args.teach_s,
                      purpose=args.purpose, train=not args.no_train)
        coach.start()
        try:
            for raw in ws:
                msg = json.loads(raw)
                if output is not None:
                    from proof.trials import record
                    record(msg,output,time.time)
                coach.on_message(msg)
        except KeyboardInterrupt:
            pass
        finally:
            coach.stop()


if __name__ == "__main__":
    main()
