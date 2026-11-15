"""Guide and independently confirm passes, unplug trials, and a post-lesson walk."""
import argparse
import json
from pathlib import Path
import re
import threading
import time

from proof.provenance import require_board
from proof.trials import record
from proof.opkey import with_key


def run(session, mode, walker, layout, send, mark, ask=input, say=print, sleep=time.sleep, clock=time.time):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}",session) or not walker.strip(): raise ValueError("use a new simple id and walker pseudonym")
    if mode not in {"crowd","tamper","walk"}: raise ValueError("choose crowd, tamper or walk")
    def command(name, **args): send(with_key({"v":2,"type":"cmd","cmd":name,"args":args}))
    def now(): return int(clock()*1000)
    def save(kind, start, **extra): mark({"v":2,"src":"live","session":session,"kind":kind,"recv_t":start,"end_t":now(),**extra})
    def wait(text, seconds):
        say(text)
        for remaining in range(seconds,0,-1):
            say(f"{remaining} s remaining")
            sleep(1)
    command("record_start",session=session,purpose="crowd" if mode=="crowd" else "heldout",walker=walker)
    try:
        if mode == "walk":
            ask("Keep the camera unplugged and the learned model unchanged. Press Enter when ready.")
            for zone in layout["zones"]:
                ask(f"Stand at the loose marker in the centre of {zone['name']}. Press Enter only once there.")
                start = now()
                wait("Stay in that zone, camera still unplugged.",6)
                ask("Confirm you stayed in that zone throughout: press Enter; Ctrl-C discards this interval.")
                save("walk",start,zone=zone["id"])
        else:
            command("arm",on=True)
            ask("Nobody inside; all devices powered. Press Enter when checked.")
            wait("Let the armed space settle empty.",20)
            if mode == "crowd":
                zone = next((z for z in layout["zones"] if z.get("still_alert_s") is not None),None)
                if zone is None: raise ValueError("layout has no no-movement alert zone")
                ask(f"One person stands still at {zone['name']}; others stay outside. Press Enter once still.")
                stationary = now()
                wait("Keep that person still. Let the genuine entry alert settle before passes.",20)
                start = now()
                for i in range(20):
                    ask(f"Pass {i+1}/20: press Enter as one walker starts passing BEHIND the strip, never entering it.")
                    passing = now()
                    wait("Walk past outside. The person inside stays still.",6)
                    ask("Confirm exactly one completed outside-only pass: Enter; Ctrl-C discards this interval.")
                    save("pass",passing)
                wait("Keep the inside person still; watch for the no-movement alert.",int(zone["still_alert_s"])+5)
                ask("Confirm all passers stayed out and the inside person stayed still throughout: Enter.")
                save("crowd",start)
                save("still",stationary,zone=zone["id"])
            else:
                node = next((n for n in layout["nodes"] if "beacon" in n.get("roles",[]) and "router" not in n.get("roles",[])),None)
                if node is None: raise ValueError("layout has no removable beacon")
                start = now()
                wait("All devices on; observe clean armed time.",20)
                for i in range(5):
                    ask(f"Unplug trial {i+1}/5: unplug {node['id']} and press Enter at that instant.")
                    unplugged = now()
                    wait("Leave it unplugged; watch for tamper.",6)
                    ask("Plug it back in now; press Enter once powered.")
                    wait("Let readings and tamper clear. Recovery is excluded from false-event exposure.",10)
                    save("unplug",unplugged,node=node["id"])
                wait("All devices on again; observe clean armed time.",20)
                ask("Confirm all five physical unplugs and restores happened as prompted: Enter.")
                save("tamper",start)
    finally:
        try:
            if mode != "walk": command("arm",on=False)
        finally: command("record_stop")


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session")
    parser.add_argument("mode",choices=["crowd","tamper","walk"])
    parser.add_argument("walker")
    args = parser.parse_args()
    require_board()
    directory = root/"data/sessions"
    if (directory/(args.session+".jsonl")).exists(): parser.error("session id already exists")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}",args.session): parser.error("use a new simple id")
    from websockets.sync.client import connect
    errors = []
    with (directory/(args.session+".states.jsonl")).open("x") as states, (directory/(args.session+".trials.jsonl")).open("x") as trials:
        with connect("ws://127.0.0.1:8765/ws") as ws:
            def receive():
                try:
                    for raw in ws: record(json.loads(raw),states,time.time)
                except Exception as error:
                    errors.append(error)
                    ws.close()
            thread = threading.Thread(target=receive,daemon=True)
            thread.start()
            def mark(row):
                trials.write(json.dumps(row,allow_nan=False)+"\n")
                trials.flush()
            try:
                run(args.session,args.mode,args.walker,json.loads((root/"radio/nodes.json").read_text()),
                    lambda msg:ws.send(json.dumps(msg)),mark)
            finally:
                ws.close()
                thread.join(timeout=3)
            if errors: raise RuntimeError("capture interrupted; incomplete exposure is unknown") from errors[0]


if __name__ == "__main__": main()
