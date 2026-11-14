"""Router placement advice (CONTRACTS.md section 6, Advice).

advise(xray, links, nodes, objects) looks at one brain state and returns the
`advice` dict from section 5, or None when there is nothing to say.

    xray     state.xray: {"w", "h", "cell_m", "origin_m", "static_db", ...}
    links    state.links: [{"id", "drop_db", ...}]
    nodes    radio/nodes.json, already parsed
    objects  state.objects: [{"xy_m", "near", "since_s", "drop_db"}]

X-ray grid layout: static_db is a flat list of w * h cells, row by row from
the south edge. Cell index i = iy * w + ix, and its centre is
origin_m + (ix + 0.5, iy + 0.5) * cell_m.

Advice fires when an object has been there for >= 5 s and its static_db peak
lies within 0.5 m of the router-to-receiver Wi-Fi line. For every router spot
except S-home we draw the new link from that spot to the receiver and add up
static_db over the cells inside its ellipse (excess path <= 0.1 m, as in
Wilson & Patwari). The spot with the lowest sum wins.

The router is assumed to sit at S-home. before_dbm and after_dbm stay null;
the brain fills them around router_moved. The advice id comes from the peak
cell and the chosen spot, so it stays the same while nothing changes.
"""
import numpy as np

WIFI_LINK = "pi5>unoq:wifi"
HOME_SPOT = "S-home"
PERSIST_S = 5.0        # the object must have been there this long
NEAR_LINK_M = 0.5      # its static_db peak must be this close to the Wi-Fi line
EXCESS_PATH_M = 0.1    # link ellipse, same as the X-ray weights
PEAK_SEARCH_M = 0.5    # look for the object's peak this far around its xy_m
WHY_DROP_DB = 3.0      # a link dropping this much counts as evidence (object rule)
NEXT_TO_M = 0.5        # an object without "near" is next to a node only this close


def advise(xray, links, nodes, objects):
    """Return the section 5 advice dict, or None."""
    if not xray or xray.get("static_db") is None or len(xray["static_db"]) == 0 or not objects:
        return None

    cx, cy, static = _grid(xray)
    node_xyz = {n["id"]: np.asarray(n["xyz_m"], dtype=float) for n in nodes["nodes"]}
    tx, rx, _ = _parse_link(WIFI_LINK)
    if tx not in node_xyz or rx not in node_xyz:
        return None
    spots = {s["id"]: np.asarray(s["xyz_m"], dtype=float) for s in nodes.get("router_spots", [])}
    home = spots.get(HOME_SPOT, node_xyz[tx])
    receiver = node_xyz[rx]
    candidates = [sid for sid in spots if sid != HOME_SPOT]
    if not candidates:
        return None

    # Pick the strongest object that has stayed long enough near the Wi-Fi line.
    best = None
    for obj in objects:
        since = obj.get("since_s")
        if since is None or since < PERSIST_S or obj.get("xy_m") is None:
            continue
        peak = _peak_near(cx, cy, static, obj["xy_m"])
        if peak is None:
            continue
        i, value = peak
        if _dist_to_segment(cx[i], cy[i], node_xyz[tx][:2], receiver[:2]) > NEAR_LINK_M:
            continue
        if best is None or value > best[2]:
            best = (obj, i, value)
    if best is None:
        return None
    obj, peak_i, _ = best

    # Score each new link: summed static_db inside its ellipse, lowest wins.
    # Ties go to the shorter move, then to the order in nodes.json.
    scored = []
    for order, sid in enumerate(candidates):
        inside = _ellipse(cx, cy, spots[sid][:2], receiver[:2])
        total = float(static[inside].sum())
        move = float(np.linalg.norm(spots[sid][:2] - home[:2]))
        scored.append((round(total, 6), round(move, 6), order, sid))
    to_spot = min(scored)[3]

    move_m = [_r2(v) for v in spots[to_spot][:2] - home[:2]]
    dist_change_m = _r2(np.linalg.norm(spots[to_spot] - receiver) - np.linalg.norm(home - receiver))
    near = obj.get("near") or _nearest_node(obj["xy_m"], node_xyz)
    why = _why(links, node_xyz, cx[peak_i], cy[peak_i])

    return {
        "id": f"a{peak_i}-{to_spot}",
        "cause": "obstruction",
        "near": near,
        "xy_m": [_r2(v) for v in obj["xy_m"][:2]],
        "link": WIFI_LINK,
        "to_spot": to_spot,
        "move_m": move_m,
        "dist_change_m": dist_change_m,
        "text": _text(near, tx, rx, nodes, move_m, home, receiver),
        "before_dbm": None,
        "after_dbm": None,
        "why": why,
    }


def _grid(xray):
    """Cell centres (x, y) and static_db as flat arrays, index iy * w + ix."""
    w, h = int(xray["w"]), int(xray["h"])
    static = np.asarray(xray["static_db"], dtype=float).ravel()
    if static.size != w * h:
        raise ValueError(f"static_db has {static.size} cells, expected {w} x {h}")
    static = np.nan_to_num(static, nan=0.0)
    cell = float(xray["cell_m"])
    ox, oy = (float(v) for v in xray["origin_m"])
    xs = ox + (np.arange(w) + 0.5) * cell
    ys = oy + (np.arange(h) + 0.5) * cell
    gx, gy = np.meshgrid(xs, ys)
    return gx.ravel(), gy.ravel(), static


def _peak_near(cx, cy, static, xy):
    """The highest positive static_db cell within PEAK_SEARCH_M of xy."""
    d = np.hypot(cx - xy[0], cy - xy[1])
    around = d <= PEAK_SEARCH_M
    if not around.any():
        around = d == d.min()
    idx = np.flatnonzero(around)
    i = int(idx[np.argmax(static[idx])])
    if static[i] <= 0:
        return None
    return i, float(static[i])


def _ellipse(cx, cy, a, b):
    """Cells whose excess path between a and b is at most EXCESS_PATH_M."""
    da = np.hypot(cx - a[0], cy - a[1])
    db = np.hypot(cx - b[0], cy - b[1])
    return da + db - float(np.linalg.norm(b - a)) <= EXCESS_PATH_M


def _dist_to_segment(px, py, a, b):
    ab = b - a
    length2 = float(ab @ ab)
    f = 0.0 if length2 == 0 else float(np.clip(((px - a[0]) * ab[0] + (py - a[1]) * ab[1]) / length2, 0.0, 1.0))
    return float(np.hypot(px - (a[0] + f * ab[0]), py - (a[1] + f * ab[1])))


def _parse_link(link_id):
    """'<tx>><rx>:<kind>' -> (tx, rx, kind)."""
    pair, _, kind = link_id.partition(":")
    tx, _, rx = pair.partition(">")
    return tx, rx, kind


def _why(links, node_xyz, px, py):
    """The Wi-Fi link first, then other links that dropped and pass near the peak."""
    found = []
    for link in links or []:
        lid = link.get("id")
        drop = link.get("drop_db")
        if lid == WIFI_LINK or drop is None or drop < WHY_DROP_DB:
            continue
        tx, rx, _ = _parse_link(lid)
        if tx not in node_xyz or rx not in node_xyz:
            continue
        if _dist_to_segment(px, py, node_xyz[tx][:2], node_xyz[rx][:2]) <= NEAR_LINK_M:
            found.append((-drop, lid))
    return [WIFI_LINK] + [lid for _, lid in sorted(found)]


def _nearest_node(xy, node_xyz):
    """The closest node within NEXT_TO_M of xy, or None."""
    p = np.asarray(xy[:2], dtype=float)
    node = min(node_xyz, key=lambda n: float(np.linalg.norm(node_xyz[n][:2] - p)))
    return node if np.linalg.norm(node_xyz[node][:2] - p) <= NEXT_TO_M else None


def _r2(v):
    return round(float(v), 2) + 0.0  # + 0.0 turns -0.0 into 0.0


def _node_name(node_id, tx, rx, nodes):
    if node_id == tx:
        return "the router"
    if node_id == rx:
        return "the receiver"
    for n in nodes["nodes"]:
        if n["id"] == node_id:
            return f"the {node_id} beacon" if "beacon" in n.get("roles", []) else f"the {node_id} node"
    return None


def _length(m):
    cm = round(abs(m) * 100)
    return f"{cm} cm" if cm < 100 else f"{abs(m):.1f} m"


def _text(near, tx, rx, nodes, move_m, home, receiver):
    """Two sentences built from the result: what is blocked, and where to move."""
    place = _node_name(near, tx, rx, nodes) if near else None
    if place == "the router":
        first = "An obstruction next to the router is blocking its link to the receiver."
    elif place == "the receiver":
        first = "An obstruction next to the receiver is blocking the router's link to it."
    elif place:
        first = f"An obstruction next to {place} is blocking the router's link to the receiver."
    else:
        first = "An obstruction between the router and the receiver is blocking their link."

    # East and west read well on the floor plan. Along y we talk about the
    # receiver instead of a compass word.
    dx, dy = move_m
    parts = []
    if round(abs(dx) * 100) > 0:
        parts.append(f"{_length(dx)} {'east' if dx > 0 else 'west'}")
    if round(abs(dy) * 100) > 0:
        toward = (dy > 0) == (receiver[1] > home[1])
        parts.append(f"{_length(dy)} {'toward' if toward else 'away from'} the receiver")
    if not parts:
        return f"{first} Leave the router where it is."
    return f"{first} Move the router {' and '.join(parts)}."
