"""Guide one unique recorded walk; prompts and commands only, never frames."""

import argparse
from contextlib import contextmanager
import json
import os
import logging
from pathlib import Path
import re
import time
import threading


from proof import layout

# Today's square: one pass over four zones is enough to train on.
SQUARE_ORDERS = {"train": (1, 3, 2, 4), "heldout": (4, 2, 3, 1), "crowd": (3, 4, 1, 2)}
MIDDLE = "middle"   # a visit to the split line between two zones (the strip layout)
OFF = "off"         # a step back off the spot, in the camera's view (a layout with one zone)


def orders(doc):
    """The zone visits per purpose, from the layout's zone ids.

    Two zones: one pass is too short to train on, so train and heldout go back and forth
    and end on the middle mark; crowd is one pass.
    """
    ids = sorted(layout.zones(doc))
    if len(ids) == 1:
        # One spot: on it and off it, so the recording holds both answers more than once.
        a = ids[0]
        return {"train": (a, OFF, a, OFF, a), "heldout": (a, OFF, a, OFF, a), "crowd": (a,)}
    if set(ids) == {1, 2, 3, 4}:
        return SQUARE_ORDERS
    if len(ids) == 2:
        a, b = ids
        return {"train": (a, b, a, b, MIDDLE), "heldout": (b, a, b, a, MIDDLE), "crowd": (b, a)}
    back = tuple(reversed(ids))
    return {"train": tuple(ids) * 2, "heldout": back * 2, "crowd": back}


def script(purpose, doc=None):
    if purpose not in {"train", "heldout", "object", "crowd"}:
        raise ValueError("purpose must be train, heldout, object or crowd")
    doc = doc or layout.load()
    strip, spot = layout.is_strip(doc), layout.is_spot(doc)
    area = "the spot" if spot else "the strip" if strip else "the square"
    steps = [(f"Nobody inside {area}. Step out completely.", 20, "off", None)]
    if purpose == "object":
        place = (f"Place the tray at T1 on the desk, then step back out of {area}." if strip
                 else "Place the tray at T1, then step outside the square.")
        return steps + [(place, 8, "off", None),
                        ("Nobody inside. Leave the tray still at T1.", 15, "object", None),
                        (f"Remove the tray and step outside {area}.", 8, "off", None),
                        (f"Nobody inside. {area[0].upper() + area[1:]} is clear.", 20, "off", None)]
    centres = layout.zones(doc)
    for zone in orders(doc)[purpose]:
        if zone == MIDDLE:
            split = doc["frame"]["zone_split_x_m"]
            steps.append((f"Walk to the middle mark, on the line between the zones (x={split} m).", 5, "person", None))
            steps.append(("Stand still on the middle mark.", 8, "person", None))
            continue
        if zone == OFF:
            steps.append(("Step back off the spot, well clear of it, and stay where the camera sees you.", 6, "person", None))
            continue
        x, y, name = centres[zone]
        if spot:
            steps.append((f"Step onto the spot ({name.lower()}): x={x} m, y={y} m.", 5, "person", None))
            steps.append(("Stand still on the spot.", 10, "person", zone if purpose == "crowd" else None))
            continue
        if strip:
            walk = f"Walk to the centre of zone {zone} ({name}), one step from the desk: x={x} m, y={y} m."
        else:
            walk = f"Walk to the centre of zone {zone} ({name}), x={x} m east, y={y} m north."
        steps.append((walk, 5, "person", None))
        steps.append((f"Stand still at the centre of zone {zone} ({name}).", 10, "person",
                      zone if purpose == "crowd" else None))
    steps.append((f"Leave {area}. Nobody inside.", 20, "off", None))
    return steps


def coach(session, purpose, walker, send, prompt=print, sleep=time.sleep, clock=time.time, object_trial=False, key=None):
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
        msg = dict(v=2, type="cmd", cmd=cmd, args=args, t=int(clock()*1000), seq=seq, src="live")
        if key:   # the board's operator key (CONTRACTS.md section 5): without it a locked board ignores us
            msg["key"] = key
        send(msg)
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
            coach(args.session, args.purpose, args.walker, lambda msg: ws.send(json.dumps(msg)), object_trial=args.object_trial,
                  key=os.environ.get("OPERATOR_KEY") or None)   # from the environment only, never a flag or a prompt


if __name__ == "__main__":
    main()
