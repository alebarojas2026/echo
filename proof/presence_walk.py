"""Record ten independently confirmed empty/occupied cycles with the camera off."""
import argparse
import csv
import json
from pathlib import Path
import re
import threading
import time

from proof.provenance import require_board


def run(session,walker,send,mark,ask=input,say=print,sleep=time.sleep,clock=time.time,ready=lambda:True,line=None):
    """line: the layout's presence line, when it has one. Then there is no model and no lesson to wait for."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}",session) or not walker.strip(): raise ValueError("use a new id and a heldout walker pseudonym")
    command = lambda cmd,**args: send({"v":2,"type":"cmd","cmd":cmd,"args":args})
    command("record_start",session=session,purpose="heldout",walker=walker)
    try:
        command("arm",on=False)
        ask("No camera and no lesson are needed on this layout. Everyone off the spot; Enter when checked." if line else
            "Unplug the camera. Use a person who was not in any lesson/training session. Everyone outside; Enter when checked.")
        for _ in range(10):
            if ready(): break
            say("Waiting for a fresh state from the brain." if line else "Waiting for a fresh camera-off state and a trained model.")
            sleep(1)
        if not ready(): raise ValueError("no fresh state from the brain; stop and fix it before recording cycles" if line else
                                         "camera-off/trained state not confirmed; stop and fix it before recording cycles")
        mark(int(clock()*1000),0)
        for i in range(10):
            say(f"Cycle {i+1}/10: stay completely outside for 60 seconds.")
            for _ in range(60): sleep(1)
            ask("Step into the sensing strip. Press Enter as entry is confirmed; no other person enters.")
            mark(int(clock()*1000),1)
            say("Stay on the spot for 60 seconds." if line else "Stay inside for 60 seconds, camera still unplugged.")
            for _ in range(60): sleep(1)
            ask("Leave completely. Press Enter as the space becomes empty.")
            mark(int(clock()*1000),0)
    finally: command("record_stop")


def fresh_ready(state,line,now_ms):
    """Ready to start the truth log: a state under a second old, with no camera running. Without a presence
    line the camera must read off and a model must be trained; with one, the line decides and no model exists."""
    if now_ms-state.get("recv_t",0)>1000: return False
    if line: return state.get("cam") not in {"on","stalled"}
    return state.get("cam")=="off" and (state.get("model") or {}).get("trained") is True


def main():
    from proof import layout as L
    line = L.presence_line(L.load())
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session")
    parser.add_argument("walker")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}",args.session): parser.error("use a new simple session id")
    require_board()
    directory = root/"data/sessions"
    if (directory/(args.session+".jsonl")).exists(): parser.error("session id already exists")
    from websockets.sync.client import connect
    errors = []
    latest = [{}]
    with (directory/(args.session+".states.jsonl")).open("x") as states, (directory/(args.session+".presence.csv")).open("x",newline="") as log:
        writer = csv.writer(log)
        writer.writerow(["recv_t","present"])
        log.flush()
        with connect("ws://127.0.0.1:8765/ws") as ws:
            def receive():
                try:
                    for raw in ws:
                        row = json.loads(raw)
                        if row.get("v")==2 and row.get("type") in {"state","event"}:
                            row["recv_t"] = int(time.time()*1000)
                            if row["type"] == "state": latest[0] = row
                            states.write(json.dumps(row,allow_nan=False)+"\n")
                            states.flush()
                except Exception as error:
                    errors.append(error)
                    ws.close()
            def mark(t,present):
                writer.writerow([t,present])
                log.flush()
            thread = threading.Thread(target=receive,daemon=True)
            thread.start()
            def ready():
                state = latest[0]
                return fresh_ready(state,line,time.time()*1000)
            try: run(args.session,args.walker,lambda m:ws.send(json.dumps(m)),mark,ready=ready,line=line)
            finally:
                ws.close()
                thread.join(timeout=3)
            if errors: raise RuntimeError("state capture interrupted; do not assume missing seconds were empty") from errors[0]


if __name__ == "__main__": main()
