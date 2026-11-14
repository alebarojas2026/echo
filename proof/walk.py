"""Guide one unique recorded walk; prompts and commands only, never frames."""

import argparse
from contextlib import contextmanager
import json
import logging
from pathlib import Path
import re
import time
import threading


CENTRES = {1: (0.5, 1.5, "Bed"), 2: (1.5, 1.5, "Chair"),
           3: (0.5, 0.5, "Hall"), 4: (1.5, 0.5, "Bathroom")}


def script(purpose):
    if purpose not in {"train", "heldout", "object", "crowd"}:
        raise ValueError("purpose must be train, heldout, object or crowd")
    steps = [("Nobody inside the square. Step out completely.", 20, "off", None)]
    if purpose == "object":
        return steps + [("Place the tray at T1, then step outside the square.", 8, "off", None),
                        ("Nobody inside. Leave the tray still at T1.", 15, "object", None),
                        ("Remove the tray and step outside the square.", 8, "off", None),
                        ("Nobody inside. The square is clear.", 20, "off", None)]
    order = (1, 3, 2, 4) if purpose == "train" else (4, 2, 3, 1) if purpose == "heldout" else (3, 4, 1, 2)
    for zone in order:
        x, y, name = CENTRES[zone]
        steps.append((f"Walk to the centre of zone {zone} ({name}), x={x} m east, y={y} m north.", 5, "person", None))
        steps.append((f"Stand still at the centre of zone {zone} ({name}).", 10, "person", zone if purpose == "crowd" else None))
    steps.append(("Leave the square. Nobody inside.", 20, "off", None))
    return steps


def coach(session, purpose, walker, send, prompt=print, sleep=time.sleep, clock=time.time, object_trial=False):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", session):
        raise ValueError("session must be a unique simple id, at most 64 characters")
    if not walker.strip():
        raise ValueError("walker id is required; use a pseudonym")
    if object_trial and purpose != "heldout":
        raise ValueError("object_trial is only for a separately recorded heldout object test")
    steps = script("object" if object_trial else purpose)
    seq = 0
    def command(cmd, args):
        nonlocal seq
        seq += 1
        send(dict(v=2, type="cmd", cmd=cmd, args=args, t=int(clock()*1000), seq=seq, src="live"))
    command("record_start", dict(session=session, purpose=purpose, walker=walker))
    try:
        for text, seconds, mode, truth in steps:
            command("label_mode", {"mode": mode})
            if truth is not None:
                command("truth", {"zone": truth})
            prompt(f"\n{text}\n{seconds} s")
            deadline = clock() + seconds
            while clock() < deadline:
                remaining = max(1, int(deadline - clock() + 0.999))
                prompt(f"{remaining} s remaining")
                sleep(min(1, max(0, deadline - clock())))
    finally:
        try:
            command("label_mode", {"mode": "off"})
        finally:
            command("record_stop", {})
    prompt("Recording stopped. Keep this session separate from every other walk.")


@contextmanager
def drain_states(ws):
    """Keep the inbound state queue moving while the coach counts down."""
    from websockets.exceptions import ConnectionClosed

    def receive():
        try:
            for _ in ws:
                pass
        except ConnectionClosed:
            # The sender reports a disconnect on its next command.
            pass
        except Exception:
            logging.getLogger(__name__).exception("walk state receiver stopped")
            ws.close()

    receiver = threading.Thread(target=receive, name="walk-state-receiver", daemon=True)
    receiver.start()
    try:
        yield
    finally:
        ws.close()
        receiver.join(timeout=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session")
    parser.add_argument("purpose", choices=["train", "heldout", "object", "crowd"])
    parser.add_argument("walker", help="pseudonymous walker id")
    parser.add_argument("--object-trial", action="store_true", help="use object prompts with heldout metadata")
    parser.add_argument("--url", default="ws://192.168.77.2:8765/ws")
    args = parser.parse_args()
    recorded = Path(__file__).resolve().parents[1] / "data/sessions" / (args.session + ".jsonl")
    if recorded.exists():
        parser.error("session already exists; use a new id and record a new physical walk")
    from websockets.sync.client import connect
    with connect(args.url) as ws:
        with drain_states(ws):
            coach(args.session, args.purpose, args.walker, lambda msg: ws.send(json.dumps(msg)), object_trial=args.object_trial)


if __name__ == "__main__":
    main()
