"""Record independent entry/empty trials and the board's state/event capture."""
import argparse
import json
import math
import re
from pathlib import Path
import threading
import time

from proof.provenance import require_board
from proof.security import hold_seconds


def run(session, walker, mode, layout, send, prompt=print, sleep=time.sleep, clock=time.time, repeats=3):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}",session): raise ValueError("use a new simple session id")
    if mode not in {"entries","empty","passes"} or not walker.strip(): raise ValueError("choose entries/empty/passes and a walker pseudonym")
    entry_s = max(6,math.ceil(hold_seconds(layout)+2))
    if mode == "passes" and hold_seconds(layout) <= 0: raise ValueError("passes need a positive armed hold")
    seq = 0
    def command(cmd,args):
        nonlocal seq
        seq += 1
        send({"v":2,"type":"cmd","seq":seq,"t":int(clock()*1000),"src":"live","cmd":cmd,"args":args})
    def wait(text, seconds):
        prompt(text)
        for remaining in range(seconds,0,-1):
            prompt(f"{remaining} s")
            sleep(1)
    command("record_start",{"session":session,"purpose":"heldout","walker":walker})
    try:
        command("label_mode",{"mode":"person"})
        command("arm",{"on":True})
        wait("Nobody inside the sensing area; verify the camera labels empty.",20)
        if mode == "empty": wait("Keep the area empty. Do not wave or place objects.",600)
        else:
            for _ in range(repeats):
                for zone in layout["zones"]:
                    text = (f"Walk straight through {zone['name']} and leave without stopping; stay inside less than {hold_seconds(layout):g} s."
                            if mode == "passes" else f"Enter the sensing area and stand at the marked centre of {zone['name']} (zone {zone['id']}).")
                    wait(text,entry_s)
                    wait("Leave the sensing area completely; stay outside.",10)
    finally:
        try: command("arm",{"on":False})
        finally:
            try: command("label_mode",{"mode":"off"})
            finally: command("record_stop",{})


def capture(ws, output, clock=time.time):
    for raw in ws:
        row = json.loads(raw)
        if row.get("v")==2 and row.get("type") in {"state","event"}:
            row["recv_t"] = int(clock()*1000)
            output.write(json.dumps(row,allow_nan=False)+"\n")
            output.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("session")
    parser.add_argument("mode",choices=["entries","empty","passes"])
    parser.add_argument("walker")
    parser.add_argument("--nodes",type=Path,default=root/"radio/nodes.json")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}",args.session): parser.error("use a new simple session id")
    require_board()  # bus timestamps and captured states must share the board clock
    directory = root/"data/sessions"
    if (directory/(args.session+".jsonl")).exists(): parser.error("session id already recorded")
    from websockets.sync.client import connect
    errors = []
    with (directory/(args.session+".states.jsonl")).open("x",encoding="utf-8") as output:
        with connect("ws://127.0.0.1:8765/ws") as ws:
            def receive():
                try: capture(ws,output)
                except Exception as error:
                    errors.append(error)
                    ws.close()
            thread = threading.Thread(target=receive,daemon=True)
            thread.start()
            try: run(args.session,args.walker,args.mode,json.loads(args.nodes.read_text()),lambda m:ws.send(json.dumps(m)))
            finally:
                ws.close()
                thread.join(timeout=3)
            if errors: raise RuntimeError("capture interrupted; do not score as a complete trial") from errors[0]


if __name__ == "__main__": main()
