"""Retrain a radio-only zone forest for each hardware subset from nodes.json."""

def subsets(layout):
    nodes = layout["nodes"]
    routers = [n["id"] for n in nodes if "router" in n.get("roles", [])]
    receivers = [n["id"] for n in nodes if "receiver" in n.get("roles", []) and n["id"] not in routers]
    if not routers or not receivers: raise ValueError("layout needs a router and a distinct receiver")
    pair = [routers[0], receivers[0]]
    four = (pair + [n["id"] for n in nodes if n["id"] not in pair])[:4]
    groups = [("all", [n["id"] for n in nodes]), ("four_nodes", four if len(four)==4 else []), ("router_receiver", pair)]
    return [(name, ids, [l["id"] for l in layout["links"] if l["tx"] in ids and l["rx"] in ids]) for name, ids in groups]


def compare(training, heldout, baseline, layout, allow_sim=False):
    from brain import features as F
    from brain.train import FOREST
    from sklearn.ensemble import RandomForestClassifier
    from proof.security import analyze

    ids = [s["meta"]["session"] for s in training+heldout]
    if len(ids)!=len(set(ids)): raise ValueError("duplicate or overlapping train/heldout ids")
    if any(s["meta"].get("purpose") not in {"train","object"} for s in training): raise ValueError("wrong training purpose")
    if any(s["meta"].get("purpose")!="heldout" for s in heldout): raise ValueError("wrong heldout purpose")
    if not allow_sim and any(m.get("src")!="live" for s in training+heldout for m in s["messages"]):
        raise ValueError("synthetic sessions are diagnostic only")
    result = []
    for name, nodes, links in subsets(layout):
        row = {"name":name,"nodes":nodes,"links":links,"zone":{"correct":None,"total":None},
               "presence":{"entries":None,"detected":None,"ci95":None}}
        result.append(row)
        if not links or any(link not in baseline for link in links): continue
        def windows(session):
            messages = [m for m in session["messages"] if m.get("type")!="rssi" or m.get("link") in links]
            return F.windows(messages, baseline, links=links)
        X, y = [], []
        for session in training:
            for window in windows(session):
                if window["label"] is not None and all(window["links"][link]["n"] for link in links):
                    X.append(F.vector(window, links=links))
                    y.append(window["label"]["zone"])
        if not X: continue
        model = RandomForestClassifier(**FOREST).fit(X, y)
        model.n_jobs = 1
        pairs, correct, total = [], 0, 0
        for session in heldout:
            capture = []
            for window in windows(session):
                if not all(window["links"][link]["n"] for link in links): continue
                zone = int(model.predict([F.vector(window, links=links)])[0])
                capture.append({"v":2,"type":"state","recv_t":window["end"],"src":"replay",
                                "health":{"status":"ok"},"pred":{"present":zone!=0,"kind":"person" if zone else "none","zone":zone}})
                if window["label"] is not None:
                    total += 1
                    correct += zone == window["label"]["zone"]
            pairs.append((session, capture))
        detection = analyze(pairs)["detection"]
        row["zone"] = {"correct":correct if total else None,"total":total or None}
        row["presence"] = {key:detection[key] for key in row["presence"]}
    return result
