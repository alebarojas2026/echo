"""Radio readings for a one-spot layout (every link marked crosses_spot in radio/nodes.json), for the soak.

The fake feed's own readings come at one rate with one noise for every link. The kit measured
something else (issue #789), so on a layout with crosses_spot lines the soak's feed makes its own:
- the Wi-Fi line across the gap (a wifi link that crosses the spot): 25 a second, noise under 1 dB,
  falls 15-21 dB with a person on the spot;
- a Bluetooth line that crosses the spot: 2-10 a second, noise 2-5 dB (dips to 4.8 dB empty), falls
  4.5-11 dB (the second opinion) or 1-10.5 dB (an unreliable one, when it ends at the router);
- lines that cross nothing: the same rates and noise, no fall.
Away from the spot a body's fall fades with its distance from the line, PERSON_WIDTH_M wide: an
assumption, not a measurement. Labels and cam messages still come from sim.fake.
Simulated; rank results, never quote them.
"""
import math
import random

PERSON_WIDTH_M = 0.2
WIFI = {"hz": (25, 25), "sd": 0.3, "cap": 0.9, "fall": (15.0, 21.0), "base": -45.0}
BLE_SECOND = {"hz": (2, 10), "sd": 1.6, "cap": 4.8, "fall": (4.5, 11.0), "base": -70.0}
BLE_WEAK = {"hz": (2, 10), "sd": 1.5, "cap": 4.5, "fall": (1.0, 10.5), "base": -72.0}


def is_gate(nodes) -> bool:
    return any(l.get("crosses_spot") is True for l in nodes["links"])


def kind_of(link: dict, nodes: dict) -> dict:
    if link["kind"] == "wifi":
        return dict(WIFI, crosses=link.get("crosses_spot") is True)
    router = next((n["id"] for n in nodes["nodes"] if "router" in n.get("roles", [])), None)
    weak = link.get("classifier") is False or link["rx"] == router
    return dict(BLE_WEAK if weak else BLE_SECOND, crosses=link.get("crosses_spot") is True)


def seg_dist(p, a, b):
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    f = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)))
    return math.dist(p, (ax + f * dx, ay + f * dy))


def readings(path, seed, nodes, layout, fake, passer_at):
    """rssi events for the whole path, every link at its own rate, in time order."""
    rng = random.Random(f"gate-{seed}")
    pos_of = {n["id"]: tuple(n["xyz_m"][:2]) for n in nodes["nodes"]}
    person = path.get("person") or []
    passers = path.get("passers") or []
    dur = float(path["duration_s"])
    out = []
    for link in nodes["links"]:
        k = kind_of(link, nodes)
        hz = rng.uniform(*k["hz"])
        step_fall = rng.uniform(*k["fall"])          # one step-on, one fall, for this path
        a, b = pos_of[link["tx"]], pos_of[link["rx"]]
        t = rng.uniform(0, 1 / hz)
        while t < dur:
            noise = max(-k["cap"], min(k["cap"], rng.gauss(0, k["sd"])))
            dbm = k["base"] + noise
            if k["crosses"]:
                p = fake.position(person, t)
                if p is not None:
                    if layout.zone_of(*p) != 0:
                        fall = step_fall
                    else:
                        fall = sum(k["fall"]) / 2 * math.exp(-(seg_dist(p, a, b) / PERSON_WIDTH_M) ** 2)
                    if fake.is_moving(person, t):
                        fall *= max(0.0, 1 + rng.gauss(0, 0.2))
                    dbm -= fall
                for q in passers:
                    qp = passer_at(q, t)
                    if qp is not None:
                        inside = layout.zone_of(*qp) != 0
                        fall = (rng.uniform(*k["fall"]) if inside else
                                sum(k["fall"]) / 2 * math.exp(-(seg_dist(qp, a, b) / PERSON_WIDTH_M) ** 2))
                        dbm -= fall * max(0.0, 1 + rng.gauss(0, 0.25))
            out.append({"type": "rssi", "t": round(t, 3), "link": link["id"], "kind": link["kind"],
                        "tx": link["tx"], "rx": link["rx"], "dbm": round(dbm)})
            t += (1 / hz) * (rng.uniform(0.9, 1.1) if k["hz"][0] == k["hz"][1] else rng.expovariate(1.0))
    out.sort(key=lambda e: e["t"])
    return out
