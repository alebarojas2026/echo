"""Specific Wi-Fi and privacy answers, using the existing frozen Ask tool names."""
import json
import math
import re
from pathlib import Path

NODES = Path(__file__).resolve().parent.parent / "radio" / "nodes.json"
INTENTS = [
    ("privacy", "model_card", r"recording me|record (me|us)|anything leaving|data.*(leav|sent|upload)|privacy|private|images? stored|cloud|internet"),
    ("weakest", "link_history", r"weakest|worst.*(?:wi.?fi|signal)|(?:wi.?fi|signal).*worst"),
    ("blocked", "explain_advice", r"(?:block|dead zone|dead spot|obstruct)"),
    ("moved", "explain_advice", r"(?=.*\b(?:router|the move|Pi B|clearing|clearance)\b)(?=.*\b(?:did|what|how|gain|result|better|improved|moving|moved)\b)"),
]


def intent(question):
    return next(((kind, tool) for kind, tool, pattern in INTENTS if re.search(pattern, question, re.I)), None)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _names(path):
    try:
        layout = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    nodes = {n["id"]: n["name"] for n in layout["nodes"]}
    return {link["id"]: f"{nodes.get(link['tx'], link['tx'])} to {nodes.get(link['rx'], link['rx'])}"
            for link in layout["links"]}


def answer(kind, store, now_ms, minutes, nodes_path=NODES, privacy_reader=None, one_spot=False):
    if kind == "privacy":
        return privacy(store, now_ms, privacy_reader)
    names = _names(nodes_path)
    if kind == "weakest":
        latest = store.latest()
        if not latest or not 0 <= now_ms - latest["t"] <= 10_000:
            return {"answer": "I have no current Wi-Fi readings, so I can't name the weakest link.", "rows": []}
        links = [{"link": link, "name": names.get(link, link), "t": latest["t"], **reading}
                 for link, reading in latest["links"].items()
                 if link.endswith(":wifi") and reading.get("status") == "ok" and _number(reading.get("drop_db"))]
        if not links:
            return {"answer": "I have no current Wi-Fi baseline comparison, so I can't name the weakest link.", "rows": []}
        row = max(links, key=lambda r: r["drop_db"])
        text = (f"The largest Wi-Fi drop is on {row['name']}: {row['drop_db']} dB below its baseline."
                if row["drop_db"] > 0 else "No Wi-Fi link is below its baseline in the latest saved reading.")
        return {"answer": text, "rows": [row]}
    seconds = [r for r in store.seconds(now_ms - minutes * 60_000) if r["t"] <= now_ms]
    if one_spot:
        return spot_recovery(seconds, nodes_path)
    events = [e for e in store.events(now_ms - minutes * 60_000, ("advice", "advice_result", "router_moved"))
              if e["t"] <= now_ms]
    if kind == "blocked":
        ids = {e["info"].get("link") for e in events if e["kind"] == "advice"}
        ids.update(r["advice"].get("link") for r in seconds if r["advice"])
        rows = []
        for link in sorted(i for i in ids if i and i.endswith(":wifi")):
            drops = [r["links"][link]["drop_db"] for r in seconds if link in r["links"]
                     and _number(r["links"][link].get("drop_db"))]
            rows.append({"link": link, "name": names.get(link, link), "max_drop_db": max(drops) if drops else None})
        if not rows:
            return {"answer": f"No dead zone was found in the saved advice for the last {minutes} minutes.", "rows": []}
        text = " ".join(f"{r['name']} had blockage advice; " +
                        (f"its largest recorded drop was {r['max_drop_db']} dB."
                         if r["max_drop_db"] is not None else "the signal drop was not recorded.") for r in rows)
        return {"answer": f"In the last {minutes} minutes: {text}", "rows": rows}
    results = [{"t": e["t"], **e["info"]} for e in events if e["kind"] == "advice_result"]
    results += [{"t": r["t"], **r["advice"]} for r in seconds if r["advice"] and r["advice"].get("after_dbm") is not None]
    results = [r for r in results if _number(r.get("before_dbm")) and _number(r.get("after_dbm"))]
    if not results:
        text = ("The router move has no measured before-and-after result yet." if any(e["kind"] == "router_moved" for e in events)
                else f"The router has not been moved in the saved records for the last {minutes} minutes.")
        return {"answer": text, "rows": []}
    last = max(results, key=lambda r: r["t"])
    row = {k: last.get(k) for k in ("t", "link", "before_dbm", "after_dbm")}
    row.update(name=names.get(row["link"], row["link"]), gain_db=round(row["after_dbm"] - row["before_dbm"], 2))
    return {"answer": f"The last measured move on {row['name']} changed the signal from {row['before_dbm']} dBm "
                      f"to {row['after_dbm']} dBm, a gain of {row['gain_db']} dB.", "rows": [row]}


def spot_recovery(seconds, nodes_path):
    """One-spot advice needs an object decision and the configured cross-gap Wi-Fi drop."""
    try:
        layout = json.loads(Path(nodes_path).read_text())
    except (OSError, ValueError):
        layout = {}
    links = {link["id"]: link for link in layout.get("links", [])
             if link.get("kind") == "wifi" and link.get("crosses_spot") is True}
    names = {node["id"]: node["name"] for node in layout.get("nodes", [])}
    told = []
    for second in seconds:
        advice = second["advice"] or {}
        reading = second["links"].get(advice.get("link"), {})
        if (second["kind"] == "object" and second["present"] == 0 and advice.get("link") in links
                and reading.get("status") == "ok" and _number(reading.get("drop_db")) and reading["drop_db"] >= 3):
            told.append(second)
    if not told:
        return {"answer": "No object blocking the Wi-Fi line was recorded in that time.", "rows": []}
    last, advice = told[-1], told[-1]["advice"]
    receiver = names.get(links[advice["link"]]["rx"], "the receiving device")
    results = [second["advice"] for second in seconds if second["t"] >= last["t"] and second["advice"]
               and second["advice"].get("id") == advice.get("id") and second["advice"].get("link") == advice["link"]
               and _number(second["advice"].get("after_dbm"))]
    measured = results[-1] if results else advice
    row = {"t": last["t"], "link": advice["link"], "receiver": receiver,
           "drop_db": last["links"][advice["link"]]["drop_db"],
           "before_dbm": measured.get("before_dbm"), "after_dbm": measured.get("after_dbm")}
    text = "Something was left in the Wi-Fi line."
    if all(_number(row[k]) for k in ("before_dbm", "after_dbm")):
        row["gain_db"] = round(row["after_dbm"] - row["before_dbm"], 2)
        text += f" The signal changed from {row['before_dbm']} to {row['after_dbm']} dBm, a gain of {row['gain_db']} dB."
    else:
        text += f" Clear the obstruction or move {receiver}; the gain has not been measured yet."
    return {"answer": text, "rows": [row]}


def privacy(store, now_ms, reader=None):
    if reader is None:
        from board.privacy import status
        reader = status
    meter = reader(now_ms=now_ms)
    latest = store.latest()
    row = {"row": "privacy", "record_interval_s": 1, "cam": latest and latest["cam"], "meter": meter}
    text = ("The board saves what the radio decided once a second, plus events, locally in SQLite. "
            "Those records contain no camera images or identities. The system is designed to run without storing images "
            "or sending data to the internet; the laptop and phone read it on our local network.")
    if row["cam"] == "on":
        text += " The latest record says the teaching camera is on for local training."
    if (meter.get("ok") is True and all(_number(meter.get(k)) and meter[k] >= 0 for k in ("images", "bytes_out", "t", "since_t"))
            and 0 <= now_ms - meter["t"] <= 10_000 and meter["since_t"] <= meter["t"]):
        text += (f" The live meter reports {meter['images']} images stored and {meter['bytes_out']} internet bytes out "
                 f"since epoch {meter['since_t']} ms.")
    else:
        text += " The live privacy count is unavailable; I can't verify the counts right now."
    return {"answer": text, "rows": [row]}
