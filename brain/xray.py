"""X-ray: a radio image of the floor square, and the objects in it.

Pure numpy, no I/O. brain/main.py feeds it every link reading as a drop
(base_dbm - dbm, on recv_t) and asks it for the "xray" and "objects" fields of
the state message (CONTRACTS.md sections 5 and 6).

Method: J. Wilson and N. Patwari, "Radio Tomographic Imaging with Wireless
Networks" (IEEE TMC, 2010). Each link is one row of W. A cell gets the weight
1/sqrt(link length) when its centre lies inside the link's ellipse (excess
path <= 0.1 m) and 0 otherwise. An image is P @ y, where y holds one value per
link and P = (W^T W + alpha I)^-1 W^T.

Per link (section 6): the static part is the drop that has held for 5 s with
the std of its 0.5 s means under 0.8 dB. It only updates while pred is not null and
pred.kind != person for the whole 5 s, so a person standing still never
becomes an object. The people part is max(0, drop - static), where drop is the
last 1 s median. static_db images the static parts, moving_db the people parts.

Cell order (CONTRACTS.md section 5): row by row from the south edge,
index = iy * w + ix, ix east from origin_m[0], iy north from origin_m[1]. Cell
(ix, iy) has its centre at origin_m + ((ix + 0.5) * cell_m, (iy + 0.5) * cell_m).
"""
from collections import deque

import numpy as np

SQUARE_M = 2.0
MARGIN_M = 0.2
NODES = {"unoq": (1.0, 2.0), "pi5": (1.0, 0.0), "east": (2.0, 1.0), "west": (0.0, 1.0)}
LINKS = ("pi5>unoq:wifi", "pi5>unoq:ble", "east>unoq:ble", "west>unoq:ble",
         "east>pi5:ble", "west>pi5:ble")
ROUTER_SPOTS = {"S-home": (1.0, 0.0), "S-W30": (0.7, 0.0), "S-E30": (1.3, 0.0)}
TRAY_SPOTS = {"T1": (1.0, 0.2)}

EXCESS_PATH_M = 0.1
ALPHA_REL = 0.1        # default alpha = this x the mean squared row length of W
DROP_WINDOW_S = 1.0    # a link's current drop is its median over this window
STATIC_S = 5.0
STATIC_STD_DB = 0.8
STATIC_BIN_S = 0.5     # the std is taken over 0.5 s means (raw readings are too noisy)
PEAK_FRAC = 0.8        # cells at or above this x the blob max give its position
BLOB_FRAC = 0.5        # cells at or above this x the image max form blobs
OBJECT_MIN_DB = 3.0    # an object needs a link with a static drop this big
OBJECT_MATCH_M = 0.5   # a peak this close to a known object is the same object
OBJECT_GRACE_S = 2.0   # an object stays listed this long after it last showed
NEAR_M = 0.5           # "near" names a node only this close, else null


def link_ends(link_id):
    """'pi5>unoq:wifi' -> ('pi5', 'unoq', 'wifi')."""
    pair, _, kind = link_id.partition(":")
    tx, _, rx = pair.partition(">")
    return tx, rx, kind


def zone_of(x, y, square_m=SQUARE_M):
    """Section 3 zone of a floor point: 1 NW, 2 NE, 3 SW, 4 SE."""
    half = square_m / 2
    return 1 + int(x >= half) + 2 * int(y < half)


class Grid:
    """w x h square cells covering the square plus the margin, centred on it."""

    def __init__(self, w=10, h=10, square_m=SQUARE_M, margin_m=MARGIN_M):
        self.w, self.h = int(w), int(h)
        span = square_m + 2 * margin_m
        self.cell_m = span / min(self.w, self.h)
        mid = square_m / 2
        self.origin_m = (mid - self.w * self.cell_m / 2, mid - self.h * self.cell_m / 2)
        xs = self.origin_m[0] + (np.arange(self.w) + 0.5) * self.cell_m
        ys = self.origin_m[1] + (np.arange(self.h) + 0.5) * self.cell_m
        gx, gy = np.meshgrid(xs, ys)  # shape (h, w), so ravel gives iy * w + ix
        self.centres = np.column_stack([gx.ravel(), gy.ravel()])

    @property
    def n(self):
        return self.w * self.h


def link_weights(a, b, centres, excess_m=EXCESS_PATH_M):
    """One row of W for a link between points a and b."""
    a = np.asarray(a, float)[:2]
    b = np.asarray(b, float)[:2]
    d = float(np.linalg.norm(b - a))
    if d == 0.0:
        return np.zeros(len(centres))
    path = np.linalg.norm(centres - a, axis=1) + np.linalg.norm(centres - b, axis=1)
    return np.where(path <= d + excess_m, 1.0 / np.sqrt(d), 0.0)


def weight_matrix(nodes, links, grid, excess_m=EXCESS_PATH_M):
    """W, shape (links, cells). nodes maps a node name to (x, y) or (x, y, z)."""
    rows = []
    for link in links:
        tx, rx, _ = link_ends(link)
        rows.append(link_weights(nodes[tx], nodes[rx], grid.centres, excess_m))
    return np.array(rows).reshape(len(rows), grid.n)


def default_alpha(W):
    sq = float(np.mean(np.sum(W * W, axis=1))) if W.size else 0.0
    return ALPHA_REL * sq if sq > 0 else 1.0


def projection(W, alpha=None):
    """P = (W^T W + alpha I)^-1 W^T, shape (cells, links).

    Computed as W^T (W W^T + alpha I)^-1. It is the same matrix, but the solve
    is links x links (6 x 6) instead of cells x cells.
    """
    if alpha is None:
        alpha = default_alpha(W)
    n_links = W.shape[0]
    return np.linalg.solve(W @ W.T + alpha * np.eye(n_links), W).T


def current_drop(t, v, now, window_s=DROP_WINDOW_S):
    """Median drop over the last window_s, or None with no reading in it."""
    recent = v[t > now - window_s]
    return float(np.median(recent)) if recent.size else None


def steady_level(t, v, now, span_s=STATIC_S, std_db=STATIC_STD_DB, bin_s=STATIC_BIN_S):
    """Median drop over the last span_s if the link held steady, else None.

    Steady means the history reaches back span_s, at least 80% of the bin_s
    bins in the window have readings, and the std of the bin means is under
    std_db.
    """
    if t.size == 0 or t[0] > now - span_s:
        return None
    keep = t > now - span_s
    t, v = t[keep], v[keep]
    k = ((t - (now - span_s)) // bin_s).astype(int)
    counts = np.bincount(k)
    if (counts > 0).sum() < max(2.0, 0.8 * span_s / bin_s):
        return None
    means = np.bincount(k, weights=v)[counts > 0] / counts[counts > 0]
    return float(np.median(v)) if means.std() < std_db else None


def blobs(img, w, h, frac=BLOB_FRAC):
    """Groups of touching cells (8-neighbours) at or above frac x the image max."""
    top = float(img.max()) if img.size else 0.0
    if top <= 0:
        return []
    on = (img >= frac * top).reshape(h, w)
    seen = np.zeros_like(on)
    out = []
    for j0, i0 in zip(*np.nonzero(on)):
        if seen[j0, i0]:
            continue
        seen[j0, i0] = True
        stack, cells = [(j0, i0)], []
        while stack:
            j, i = stack.pop()
            cells.append(j * w + i)
            for y in range(max(j - 1, 0), min(j + 2, h)):
                for x in range(max(i - 1, 0), min(i + 2, w)):
                    if on[y, x] and not seen[y, x]:
                        seen[y, x] = True
                        stack.append((y, x))
        out.append(np.array(sorted(cells)))
    return out


def hot_spot(img, centres, cells=None, frac=PEAK_FRAC):
    """Value-weighted centre of the cells at or above frac x the max.

    cells limits the search to one blob. None when nothing is above 0.
    """
    idx = np.arange(len(img)) if cells is None else np.asarray(cells)
    vals = img[idx]
    top = float(vals.max()) if vals.size else 0.0
    if top <= 0:
        return None
    pick = idx[vals >= frac * top]
    wts = img[pick]
    x, y = (centres[pick] * wts[:, None]).sum(axis=0) / wts.sum()
    return float(x), float(y)


def _dist(a, b):
    return float(np.hypot(a[0] - b[0], a[1] - b[1]))


class Xray:
    """Per-link drop histories in, section 5 "xray" and "objects" out.

        xr = Xray.from_nodes(nodes_doc)      # radio/nodes.json, 10 x 10
        xr.add(link, recv_t_ms, drop_db)     # every reading
        out = xr.update(now_ms, kind)        # about 10 times a second; kind = pred.kind or None
        state["xray"], state["objects"] = out["xray"], out["objects"]
        xr.set_router(spot)                  # on router_moved / router_home
        xr.reset()                           # after a new baseline
    """

    def __init__(self, nodes=None, links=LINKS, w=10, h=10, alpha=None,
                 excess_m=EXCESS_PATH_M, router_spots=None, square_m=SQUARE_M):
        self.nodes = {k: (float(p[0]), float(p[1])) for k, p in (nodes or NODES).items()}
        self.links = list(links)
        self.router_spots = dict(router_spots or ROUTER_SPOTS)
        self.square_m = square_m
        self.grid = Grid(w, h, square_m=square_m)
        self.alpha = alpha
        self.excess_m = excess_m
        self.rebuild()
        self.reset()

    @classmethod
    def from_nodes(cls, doc, **kw):
        """Build from radio/nodes.json, already parsed. kw: w, h, alpha, excess_m."""
        return cls({n["id"]: n["xyz_m"] for n in doc["nodes"]},
                   [link["id"] for link in doc["links"]],
                   router_spots={s["id"]: s["xyz_m"][:2] for s in doc.get("router_spots", [])},
                   square_m=float(doc.get("frame", {}).get("size_m", [SQUARE_M])[0]), **kw)

    def rebuild(self):
        """Recompute W and P from the current node positions."""
        self.W = weight_matrix(self.nodes, self.links, self.grid, self.excess_m)
        self.P = projection(self.W, self.alpha)

    def move_node(self, node, xy):
        self.nodes[node] = (float(xy[0]), float(xy[1]))
        self.rebuild()

    def set_router(self, spot):
        """router_moved {spot} or router_home ("S-home"): move pi5 and rebuild P."""
        self.move_node("pi5", self.router_spots[spot])

    def reset(self):
        """Forget histories, static levels and objects (after a new baseline)."""
        self._hist = {link: deque(maxlen=2048) for link in self.links}   # (t_s, drop_db)
        self.static_link_db = np.zeros(len(self.links))
        self._objects = []
        self._frozen_t = float("-inf")   # last tick with pred null or a person

    def add(self, link, t_ms, drop_db):
        hist = self._hist.get(link)
        if hist is not None:
            hist.append((t_ms / 1000.0, float(drop_db)))

    def link_levels(self, now_s, kind=None):
        """Per-link people parts, static parts and the count of links heard in 1 s."""
        if kind is None or kind == "person":
            self._frozen_t = now_s
        may_update = now_s - self._frozen_t >= STATIC_S
        people = np.zeros(len(self.links))
        fresh = 0
        for k, link in enumerate(self.links):
            hist = self._hist[link]
            while len(hist) > 1 and hist[1][0] <= now_s - STATIC_S:
                hist.popleft()   # keeps one reading at or before the 5 s window
            t, v = np.array(hist).reshape(-1, 2).T
            if may_update:
                level = steady_level(t, v, now_s)
                if level is not None:
                    self.static_link_db[k] = level
            drop = current_drop(t, v, now_s)
            if drop is not None:
                fresh += 1
                people[k] = max(0.0, drop - self.static_link_db[k])
        return people, np.maximum(self.static_link_db, 0.0), fresh

    def image(self, link_db):
        return np.maximum(self.P @ link_db, 0.0)

    def update(self, now_ms, kind=None):
        """One tick. kind = pred.kind ("person" | "object" | "none"), or None
        while pred is null. Returns {"xray": ..., "objects": [...], "events": [...]}.

        events are object_on / object_off as {"kind", "info"} for the event stream.
        """
        now = now_ms / 1000.0
        people, static, fresh = self.link_levels(now, kind)
        mov_img, sta_img = self.image(people), self.image(static)
        g = self.grid
        xray = {"w": g.w, "h": g.h, "cell_m": round(g.cell_m, 4),
                "origin_m": [round(g.origin_m[0], 4), round(g.origin_m[1], 4)],
                "moving_db": np.round(mov_img, 2).tolist(),
                "static_db": np.round(sta_img, 2).tolist(),
                "n_links": fresh}
        events = self._track(self._find_objects(sta_img, static), now)
        objects = [{"xy_m": [round(o["xy"][0], 2), round(o["xy"][1], 2)], "near": o["near"],
                    "since_s": round(now - o["first"], 1), "drop_db": round(o["drop"], 1)}
                   for o in self._objects]
        return {"xray": xray, "objects": objects, "events": events}

    def nearest_node(self, xy, within_m=NEAR_M):
        """The closest node if it is within within_m of xy, else None."""
        best = min(self.nodes, key=lambda n: _dist(self.nodes[n], xy))
        return best if _dist(self.nodes[best], xy) <= within_m else None

    def _find_objects(self, img, static):
        if static.max(initial=0.0) < OBJECT_MIN_DB:
            return []
        found = []
        for cells in blobs(img, self.grid.w, self.grid.h):
            xy = hot_spot(img, self.grid.centres, cells)
            peak = cells[int(np.argmax(img[cells]))]
            on_peak = np.nonzero(self.W[:, peak] > 0)[0]
            if xy is None or on_peak.size == 0:
                continue
            k = on_peak[int(np.argmax(static[on_peak]))]
            if static[k] >= OBJECT_MIN_DB:
                found.append({"xy": xy, "near": self.nearest_node(xy),
                              "drop": float(static[k]), "link": self.links[k]})
        return found

    def _track(self, found, now):
        events, free = [], list(self._objects)
        for f in found:
            match = min(free, default=None, key=lambda o: _dist(o["xy"], f["xy"]))
            if match is not None and _dist(match["xy"], f["xy"]) < OBJECT_MATCH_M:
                free.remove(match)
                match.update(f, last=now)
            else:
                self._objects.append(dict(f, first=now, last=now))
                events.append(self._event("object_on", f))
        for o in free:
            if now - o["last"] > OBJECT_GRACE_S:
                self._objects.remove(o)
                events.append(self._event("object_off", o))
        return events

    def _event(self, kind, o):
        x, y = o["xy"]
        return {"kind": kind, "info": {"node": o["near"], "link": o["link"],
                                       "zone": zone_of(x, y, self.square_m),
                                       "xy_m": [round(x, 2), round(y, 2)],
                                       "drop_db": round(o["drop"], 1)}}
