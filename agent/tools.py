"""The questions the room can answer. Each tool reads the store and returns
{"answer": text, "rows": [...]}: the answer is a template filled from those rows, so
every number in it is in a row (or is the number of minutes that was asked for).
"""
import statistics
import time
import json
from pathlib import Path

GAP_MS = 2000   # saved seconds this close together are one span
NODES_JSON = Path(__file__).resolve().parent.parent / "radio" / "nodes.json"


def clock(t_ms: int) -> str:
    return time.strftime("%H:%M:%S", time.localtime(t_ms / 1000))


def _last(minutes) -> str:
    return "the last minute" if minutes == 1 else f"the last {minutes} minutes"


def place(name: str, only: bool):
    """How an answer says a zone by its name alone, or None when it has no such words. A name that is already a
    place ("At the desk") is said as it is; the only zone in the layout with any other name is just "here"."""
    words = name.strip()
    if words.split(" ")[0].lower() in ("at", "by", "in", "on"):
        return words[0].lower() + words[1:]
    return "here" if only else None


def _where(zone, zones) -> str:
    if zone not in zones:
        return "here"
    return place(zones[zone], len(zones) == 1) or f"in {zones[zone]}"


def _spans(rows: list, zones: dict) -> list:
    """Runs of saved seconds in one zone, as rows: {zone, name, from, to, seconds}."""
    out = []
    for r in rows:
        last = out[-1] if out else None
        if last and last["zone"] == r["zone"] and r["t"] - last["_end"] <= GAP_MS:
            last["_end"], last["seconds"] = r["t"], last["seconds"] + 1
        else:
            out.append({"zone": r["zone"], "name": zones.get(r["zone"]), "_start": r["t"], "_end": r["t"], "seconds": 1})
    return [{"zone": s["zone"], "name": s["name"], "from": clock(s["_start"]), "to": clock(s["_end"]),
             "seconds": s["seconds"], "from_t": s["_start"], "to_t": s["_end"]} for s in out]


def _span(from_t: int, to_t: int, now_ms: int, before_ms: int = 0, after_ms: int = 0) -> dict:
    """The stretch an answer is about (section 10), for the screen's Replay button: never past now."""
    return {"from_t": from_t - before_ms, "to_t": min(to_t + after_ms, max(now_ms, to_t))}


def _window(store, now_ms, minutes):
    return store.seconds(now_ms - minutes * 60_000)


def _person(r, zone=None) -> bool:
    return r["present"] == 1 and r["kind"] == "person" and (zone is None or r["zone"] == zone)


def current_spot(store, now_ms, zones, nodes_path=None):
    """The latest decision, without turning a missing decision into an empty desk."""
    row = store.latest()
    if not row or not 0 <= now_ms - row["t"] <= 5000 or row["present"] is None or row["health"] == "blind":
        return {"answer": "I have no current decision for the desk.", "rows": []}
    where = _where(next(iter(zones)), zones)
    if _person(row):
        motion = {"still": "standing still", "moving": "moving"}.get(row["motion"])
        text = f"Someone is {where}" + (f", {motion}." if motion else ".")
    elif row["kind"] == "object" and row["present"] == 0 and _wifi_drop(row, nodes_path=nodes_path):
        text = "Something was left in the Wi-Fi line; nobody is detected at the desk."
    elif row["present"] != 0:
        text = "I have no current decision for the desk."
    else:
        text = f"Nobody is detected {where}."
    return {"answer": text, "rows": [{k: row[k] for k in ("t", "present", "kind", "zone", "motion")} ]}


def _wifi_drop(row, link=None, nodes_path=None):
    try:
        crossing = {item["id"] for item in json.loads(Path(nodes_path or NODES_JSON).read_text())["links"]
                    if item.get("kind") == "wifi" and item.get("crosses_spot") is True}
    except (OSError, ValueError, KeyError):
        crossing = set()
    return any(key in crossing and (link is None or key == link) and reading.get("status") == "ok"
               and isinstance(reading.get("drop_db"), (int, float)) and reading["drop_db"] >= 3
               for key, reading in row["links"].items())


def spot_advice(store, now_ms, zones, minutes=10, nodes_path=None):
    """An object decision and a weak Wi-Fi line must agree before calling it an obstruction."""
    rows = [r for r in store.seconds(now_ms - minutes * 60_000) if r["t"] <= now_ms]
    told = [r for r in rows if r["kind"] == "object" and r["present"] == 0 and r["advice"] and r["advice"].get("link")
            and _wifi_drop(r, r["advice"].get("link"), nodes_path)]
    if not told:
        return {"answer": "No object blocking the Wi-Fi line was recorded in that time.", "rows": []}
    last = told[-1]
    advice = last["advice"]
    link = advice["link"]
    receiver = link.split(">", 1)[-1].split(":", 1)[0]
    try:
        names = {node["id"]: node["name"] for node in json.loads(Path(nodes_path or NODES_JSON).read_text())["nodes"]}
    except (OSError, ValueError, KeyError):
        names = {}
    receiver = names.get(receiver, "the receiving device")
    row = {"t": last["t"], "link": link, "receiver": receiver, "drop_db": last["links"][link]["drop_db"],
           "before_dbm": advice.get("before_dbm"), "after_dbm": advice.get("after_dbm")}
    results = [r["advice"] for r in rows if r["advice"] and r["advice"].get("id") == advice.get("id")
               and r["advice"].get("link") == link and r["t"] >= last["t"] and r["advice"].get("after_dbm") is not None]
    if results:
        row.update({k: results[-1].get(k) for k in ("before_dbm", "after_dbm")})
    text = "Something was left in the Wi-Fi line."
    if all(isinstance(row[k], (int, float)) for k in ("before_dbm", "after_dbm")):
        row["gain_db"] = round(row["after_dbm"] - row["before_dbm"], 2)
        text += (f" The recorded signal changed from {row['before_dbm']} to {row['after_dbm']} dBm, "
                 f"a gain of {row['gain_db']} dB.")
    else:
        text += f" Clear the obstruction or move {receiver}; the gain has not been measured yet."
    return {"answer": text, "rows": [row]}


def _unknown(rows) -> tuple:
    n = sum(r["present"] is None for r in rows)
    return n, (f" For {n} s of that time there was no prediction, so I can't say." if n else "")


def presence(store, now_ms, zones, minutes=10, zone=None, **_):
    """was anyone here (or in one zone) in the last N minutes"""
    rows = _window(store, now_ms, minutes)
    if not rows:
        return {"answer": f"I have no records for {_last(minutes)}.", "rows": []}
    spans = _spans([r for r in rows if _person(r, zone)], zones)
    unknown, note = _unknown(rows)
    summary = {"row": "summary", "seconds_with_someone": sum(s["seconds"] for s in spans),
               "seconds_without_prediction": unknown, "seconds_saved": len(rows)}
    if not spans:
        return {"answer": f"No. Nobody was seen {_where(zone, zones)} in {_last(minutes)}.{note}",
                "rows": [summary]}
    last = spans[-1]
    return {"answer": f"Yes. Someone was {_where(zone, zones)} for {summary['seconds_with_someone']} s of "
                      f"{_last(minutes)}, most recently {_where(last['zone'], zones)} from {last['from']} to "
                      f"{last['to']}.{note}", "rows": [summary] + spans,
            "span": _span(last["from_t"], last["to_t"], now_ms, 5000, 5000)}


def still_spans(store, now_ms, zones, minutes=10, **_):
    """how long someone stayed without moving"""
    rows = [r for r in _window(store, now_ms, minutes) if _person(r) and r["motion"] == "still"]
    spans = _spans(rows, zones)
    if not spans:
        return {"answer": f"I have no record of someone staying still in {_last(minutes)}.", "rows": []}
    longest = max(spans, key=lambda s: s["seconds"])
    return {"answer": f"The longest time without movement was {longest['seconds']} s {_where(longest['zone'], zones)}, "
                      f"from {longest['from']} to {longest['to']}.", "rows": spans,
            "span": _span(longest["from_t"], longest["to_t"], now_ms, 5000, 5000)}


def _event_rows(store, now_ms, minutes, kinds, zones):
    return [{"at": clock(e["t"]), "t": e["t"], "kind": e["kind"], **e["info"],
             **({"name": zones[e["info"]["zone"]]} if e["info"].get("zone") in zones else {})}
            for e in store.events(now_ms - minutes * 60_000, kinds)]


def alerts(store, now_ms, zones, minutes=10, **_):
    """no-movement alerts and check-ins"""
    rows = _event_rows(store, now_ms, minutes, ("alert_on", "alert_off", "checkin"), zones)
    on = [r for r in rows if r["kind"] == "alert_on"]
    if not on:
        return {"answer": f"No no-movement alert was raised in {_last(minutes)}.", "rows": rows}
    last = on[-1]
    after = [r for r in rows[rows.index(last):] if r["kind"] == "alert_off"]
    cleared = f" and it cleared at {after[0]['at']}" if after else " and it has not cleared"
    summary = {"row": "summary", "alerts": len(on)}
    return {"answer": f"No-movement alerts in {_last(minutes)}: {len(on)}. The last one was "
                      f"{_where(last.get('zone'), zones)} at {last['at']}{cleared}.", "rows": [summary] + rows,
            "span": _span(last["t"], after[0]["t"] if after else last["t"], now_ms, 20_000, 10_000)}


def intrusions(store, now_ms, zones, minutes=10, **_):
    """intrusion alerts while the space was armed"""
    rows = _event_rows(store, now_ms, minutes, ("armed", "disarmed", "intrusion"), zones)
    hits = [r for r in rows if r["kind"] == "intrusion"]
    latest = store.latest()
    armed = "armed" if latest and latest["armed"] else "not armed"
    if not hits:
        return {"answer": f"No intrusion alert in {_last(minutes)}. The space is {armed} now.", "rows": rows}
    last = hits[-1]
    place = _where(last.get("zone"), zones) if "zone" in last else f"on the path {last.get('link')}"
    summary = {"row": "summary", "intrusion_alerts": len(hits)}
    return {"answer": f"Intrusion alerts in {_last(minutes)}: {len(hits)}. The last one was {place} at "
                      f"{last['at']}. The space is {armed} now.", "rows": [summary] + rows,
            "span": _span(last["t"], last["t"], now_ms, 10_000, 30_000)}


def link_history(store, now_ms, zones, minutes=10, link=None, **_):
    """how a radio link has been reading, and when it was blind"""
    seconds = _window(store, now_ms, minutes)
    ids = [link] if link else sorted({i for r in seconds for i in r["links"]})
    rows = []
    for i in ids:
        dbm = [r["links"][i]["dbm"] for r in seconds if i in r["links"] and r["links"][i]["dbm"] is not None]
        if dbm:
            rows.append({"link": i, "min_dbm": min(dbm), "median_dbm": round(statistics.median(dbm), 1),
                         "max_dbm": max(dbm), "seconds_blind": sum(i in r["blind"] for r in seconds)})
    if not rows:
        return {"answer": f"I have no readings for {link or 'any link'} in {_last(minutes)}.", "rows": []}
    text = " ".join(f"{r['link']} read {r['min_dbm']} to {r['max_dbm']} dBm (median {r['median_dbm']}) and was "
                    f"blind for {r['seconds_blind']} s." for r in rows)
    return {"answer": f"In {_last(minutes)}: {text}", "rows": rows}


def explain_advice(store, now_ms, zones, minutes=10, **_):
    """the last router advice and what the move changed"""
    if len(zones) == 1:
        return spot_advice(store, now_ms, zones, minutes=minutes, nodes_path=_.get("nodes_path"))
    told = [r for r in store.seconds(now_ms - minutes * 60_000, now_ms) if r["advice"]]
    if not told:
        return {"answer": "No router advice has been given.", "rows": []}
    advice = told[-1]["advice"]
    row = {"at": clock(told[-1]["t"]), **{k: advice.get(k) for k in ("text", "link", "to_spot", "before_dbm", "after_dbm")}}
    result = ""
    if row["after_dbm"] is not None:
        result = f" The link read {row['before_dbm']} dBm before the move and {row['after_dbm']} dBm after it."
    return {"answer": f"The last advice was: {row['text']}{result}", "rows": [row]}


def model_card(store, now_ms, zones, **_):
    """what model runs on the board"""
    latest = store.latest()
    model = latest and latest["model"]
    if not model or not model.get("trained"):
        return {"answer": "No model is trained on this board yet.", "rows": [model] if model else []}
    row = {"ver": model.get("ver"), "windows": model.get("windows"), "sessions": len(model.get("train_sessions") or []),
           "train_s": model.get("train_s"), "ms_per_decision": model.get("ms_per_decision")}
    took = "the training time was not measured" if row["train_s"] is None else f"training took {row['train_s']} s"
    speed = ("the time per decision was not measured" if row["ms_per_decision"] is None
             else f"one decision takes {row['ms_per_decision']} ms")
    return {"answer": f"Model {row['ver']} runs on this board, trained on {row['windows']} windows from "
                      f"{row['sessions']} sessions; {took}, and {speed}.", "rows": [row]}


TOOLS = {f.__name__: f for f in (presence, still_spans, alerts, intrusions, link_history, explain_advice, model_card)}
