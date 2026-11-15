"""A physics-informed link model for the lab. SIMULATED data, dev only.

Closer to a real room than sim/fake.py, so the brain can be pushed until it
breaks. It reuses the room (nodes, links, zones) from sim/fake.py and writes
CONTRACTS.md v2 messages that already carry the bus's recv_t.

Per reading, the field at the receiver is

    E = 10^(-shadow/20) + scatter + diffuse,   dBm = level + 20 log10|E| + drift + offsets + noise

- level: log-distance path loss with a per-link fixed offset;
- shadow: knife-edge loss of each body near the link line. The edge sits at
  width/2 from the body's centre, the Fresnel radius sets how soft the edge
  is, and the loss is scaled so a body centred on the line gives `depth_db`.
  Bodies shorter than the top of the Fresnel zone block less;
- scatter: the ray a body reflects, with a phase set by its excess path, so
  a moving body makes the link flutter and a still one shifts it a little;
- diffuse: the rest of the hall, a Rician part with factor K that changes
  over `coherence_s`;
- drift: slow wander per link and per phone; BLE adds a fixed offset per
  advertising channel; readings are rounded to 1 dB.
Sampling: Wi-Fi is polled about 20/s and repeats the last heard frame; phone
beacons advertise 7-10/s and each scanner misses some adverts; the Pi beacon
advertises about 20/s; loss comes in bursts. The camera teacher adds missed
frames, foot-point noise, clipping and latency.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
from scipy.signal import lfilter
from scipy.special import fresnel

from sim.fake import LINKS as SIM_LINKS
from sim.fake import NODES, link_id, zone_of

LINKS = [link_id(*lk) for lk in SIM_LINKS]
ENDS = {link_id(*lk): (lk[0], lk[1]) for lk in SIM_LINKS}
KIND = {link_id(*lk): lk[2] for lk in SIM_LINKS}
WIFI = "pi5>unoq:wifi"
SIZE = 2.0
NODE_Z = 1.0
DT = 0.01                       # timeline step, s
LAMBDA_M = {"wifi": 0.058, "ble": 0.125}
REF_DBM = {"wifi": -38.0, "pi5": -56.0, "phone": -62.0}   # level at 1 m
T0_MS = 1_763_149_500_000


@dataclass
class Env:
    """Everything about the room and the radios that the lab varies."""
    k_db: float = 15.0          # Rician K of the hall (low = busy hall, more fading)
    coherence_s: float = 1.0
    meas_db: float = 0.5        # per-reading estimation noise
    ble_chan_db: float = 1.5    # std of the per-channel offset on BLE links
    drift_db: float = 0.5       # slow wander, std
    drift_tau_s: float = 120.0
    pl_exp: float = 2.2
    offset_db: float = 3.0      # fixed per-link offset (antenna pattern, phone case)
    scatter: float = 0.2       # a body's reflected ray, relative to the direct ray
    hand_db: float = 4.0        # a forearm and hand centred on a link
    bystanders: int = 1         # people walking just outside the square
    bystander_m: tuple = (0.6, 1.5)   # how far outside the square they walk
    wifi_poll_hz: float = 20.0
    wifi_jitter_ms: float = 10.0
    wifi_frame_hz: float = 40.0  # frames the board hears from the Pi; a poll repeats the last one
    phone_hz: float = 8.5
    phone_miss: float = 0.15
    pi_ble_hz: float = 20.0
    pi_ble_miss: float = 0.05
    burst_per_min: float = 2.0   # interference bursts per receiver and band
    burst_s: float = 0.6
    throttle_per_min: float = 0.0  # a phone slows to ~1 advert/s (screen off, app in background)
    cam_fps: float = 7.5
    cam_miss: float = 0.05
    cam_latency_ms: float = 120.0
    foot_noise_m: float = 0.05
    foot_bias_m: float = 0.03
    det_miss: float = 0.03
    clip_m: float = 0.08
    cam_view_m: float = 0.3      # the camera sees this far beyond the square

    def to_dict(self):
        return asdict(self)


@dataclass
class Person:
    height_m: float = 1.75
    width_m: float = 0.4
    speed: float = 0.9
    depth_db: float = 8.0
    sway_m: float = 0.01

    @classmethod
    def draw(cls, rng, **fixed):
        h = fixed.get("height_m", rng.uniform(1.5, 1.95))
        p = cls(height_m=h, width_m=float(np.clip(0.4 + 0.2 * (h - 1.72) + rng.normal(0, 0.04), 0.3, 0.5)),
                speed=rng.uniform(0.5, 1.3), depth_db=rng.uniform(4.0, 12.0), sway_m=rng.uniform(0.005, 0.02))
        for k, v in fixed.items():
            setattr(p, k, v)
        return p


def knife_edge_db(nu):
    """Exact single knife-edge loss from the Fresnel integrals (negative = the +1.2 dB lobe)."""
    S, C = fresnel(np.asarray(nu, float))
    return -10 * np.log10(0.5 * ((0.5 - C) ** 2 + (0.5 - S) ** 2))


def geometry(px, py, a, b):
    """Along-link fraction f, distance r to the line, d1, d2 and excess path e."""
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    D = math.hypot(dx, dy)
    f = ((px - ax) * dx + (py - ay) * dy) / (D * D)
    r = np.abs((px - ax) * dy - (py - ay) * dx) / D
    da = np.hypot(px - ax, py - ay)
    db = np.hypot(px - bx, py - by)
    return f, r, f * D, (1 - f) * D, da + db - D


def shadow_db(px, py, a, b, lam, width, depth, height=None):
    """Loss of a body of `width` centred at (px, py); nan positions give 0."""
    f, r, d1, d2, _ = geometry(px, py, a, b)
    inside = (f > 0.01) & (f < 0.99) & np.isfinite(r)
    d1 = np.where(inside, d1, 1.0)
    d2 = np.where(inside, d2, 1.0)
    rf = np.sqrt(lam * d1 * d2 / (d1 + d2))
    nu = (width / 2 - np.where(inside, r, 9.0)) * math.sqrt(2) / rf
    nu_c = (width / 2) * math.sqrt(2) / rf
    J = knife_edge_db(nu)
    # Scaled so a centred body loses `depth`; outside the body the small diffraction
    # gain (J < 0) is kept as is.
    loss = np.where(J >= 0, depth * np.clip(J / knife_edge_db(nu_c), 0.0, 1.0), J)
    if height is not None:   # the body only blocks the Fresnel zone up to its height
        loss = loss * np.clip((height - (NODE_Z - rf)) / (2 * rf), 0.0, 1.0)
    return np.where(inside, loss, 0.0)


SCATTER_PEAK_M = 0.2   # excess path where a body's reflection is strongest


def scatter_field(px, py, a, b, lam, rho, phase0=0.0):
    """Reflected ray from a body beside the link; its phase follows the excess path.

    On the line itself the body diffracts rather than reflects (shadow_db has
    that), so the amplitude is 0 at zero excess path, rho at SCATTER_PEAK_M,
    and fades beyond.
    """
    _, _, _, _, e = geometry(px, py, a, b)
    ok = np.isfinite(e)
    e = np.where(ok, e, 10.0)
    u = e / SCATTER_PEAK_M
    return np.where(ok, rho * u * np.exp(1 - u) * np.exp(1j * (2 * np.pi * e / lam + phase0)), 0)


class Script:
    """What happens in and around the square, one sample every DT seconds."""

    def __init__(self, rng, env: Env):
        self.rng, self.env = rng, env
        self.x, self.y, self.hx, self.hy, self.who = [], [], [], [], []
        self.mode, self.cam = [], []
        self.persons: list = []
        self.objects: list = []      # {x, y, width_m, depth_db, t_on, t_off}
        self.outages: list = []      # {node | link, t_on, t_off}
        self.marks: list = []        # (t, tag, info)
        self.cur = None
        self.pid = -1
        self.label_mode = "off"
        self.camera = "on"

    @property
    def t(self) -> float:
        return len(self.x) * DT

    def mark(self, tag, **info):
        self.marks.append((self.t, tag, info))

    def _push(self, xs, ys, hx=None, hy=None):
        n = len(xs)
        self.x += list(xs)
        self.y += list(ys)
        self.hx += list(hx) if hx is not None else [np.nan] * n
        self.hy += list(hy) if hy is not None else [np.nan] * n
        self.who += [self.pid if self.cur is not None else -1] * n
        self.mode += [self.label_mode] * n
        self.cam += [self.camera] * n

    def idle(self, s):
        n = int(round(s / DT))
        if self.cur is None:
            self._push([np.nan] * n, [np.nan] * n)
        else:
            self.stand(s)

    def enter(self, person: Person, at=None):
        """A person appears just outside a random edge (away from the nodes)."""
        self.persons.append(person)
        self.pid = len(self.persons) - 1
        if at is None:
            u = self.rng.choice([0.25, 0.6, 1.4, 1.75])
            side = self.rng.integers(4)
            at = [(u, -0.5), (u, SIZE + 0.5), (-0.5, u), (SIZE + 0.5, u)][side]
        self.cur = np.array(at, float)

    def walk_to(self, x, y):
        p = self.persons[self.pid]
        goal = np.array([x, y], float)
        d = float(np.linalg.norm(goal - self.cur))
        if d < 1e-6:
            return
        v = p.speed * self.rng.uniform(0.85, 1.15)
        n = max(2, int(d / v / DT))
        s = np.linspace(0, 1, n + 1)[1:]
        head = (goal - self.cur) / d
        side = np.array([-head[1], head[0]])
        gait = 0.02 * np.sin(2 * np.pi * 0.9 * np.arange(n) * DT) * np.sin(np.pi * s)  # step sway
        pts = self.cur + np.outer(s, goal - self.cur) + np.outer(gait, side)
        self._push(pts[:, 0], pts[:, 1])
        self.cur = goal

    def _sway(self, n, sigma):
        a = math.exp(-DT / 2.0)
        w = self.rng.normal(0, sigma * math.sqrt(1 - a * a), (n, 2))
        return lfilter([1.0], [1.0, -a], w, axis=0)

    def stand(self, s):
        n = int(round(s / DT))
        sw = self._sway(n, self.persons[self.pid].sway_m)
        self._push(self.cur[0] + sw[:, 0], self.cur[1] + sw[:, 1])

    def wave(self, s, hz=2.0, link=WIFI):
        """Stand and swing a hand toward and away from a link line."""
        p = self.persons[self.pid]
        n = int(round(s / DT))
        a, b = (np.array(NODES[k]) for k in ENDS[link])
        ab = (b - a) / np.linalg.norm(b - a)
        rel = self.cur - a
        foot = a + ab * float(rel @ ab)
        toward = foot - self.cur
        toward = toward / (np.linalg.norm(toward) or 1.0)
        reach = 0.44 * p.height_m * self.rng.uniform(0.5, 0.8)   # forearm and hand swing
        f = hz * (1 + 0.08 * np.cumsum(self.rng.normal(0, 0.02, n)))   # people are not metronomes
        amp = reach * (0.5 + 0.5 * np.sin(2 * np.pi * np.cumsum(f) * DT + self.rng.uniform(0, 6.3)))
        base = self.cur + toward * 0.15
        hand = base + np.outer(amp, toward)
        sw = self._sway(n, p.sway_m)
        self._push(self.cur[0] + sw[:, 0], self.cur[1] + sw[:, 1], hand[:, 0], hand[:, 1])
        self.mark("wave", t_on=self.t - n * DT, hz=hz, dist_m=float(np.linalg.norm(foot - self.cur)))

    def leave(self):
        x, y = self.cur
        exits = [(x, -0.6), (x, SIZE + 0.6), (-0.6, y), (SIZE + 0.6, y)]
        d = [abs(y), abs(SIZE - y), abs(x), abs(SIZE - x)]
        k = int(np.argmin([di + (0.6 if abs(e[0] - 1) < 0.25 or abs(e[1] - 1) < 0.25 else 0)
                           for di, e in zip(d, exits)]))   # avoid stepping over a node
        self.walk_to(*exits[k])
        self.cur = None

    def place(self, x, y, width_m=0.3, depth_db=10.0):
        self.objects.append({"x": x, "y": y, "width_m": width_m, "depth_db": depth_db,
                             "t_on": self.t, "t_off": math.inf})

    def remove_objects(self):
        for o in self.objects:
            o["t_off"] = min(o["t_off"], self.t)

    def outage(self, s, node=None, link=None):
        """A node or link goes silent for s seconds from now (time keeps running in parallel)."""
        self.outages.append({"node": node, "link": link, "t_on": self.t, "t_off": self.t + s})


class Timeline:
    """Script arrays plus bystanders, ready for sampling."""

    def __init__(self, sc: Script):
        self.env, self.rng = sc.env, sc.rng
        self.x, self.y = np.array(sc.x), np.array(sc.y)
        self.hx, self.hy = np.array(sc.hx), np.array(sc.hy)
        self.who = np.array(sc.who)
        self.mode, self.cam = np.array(sc.mode), np.array(sc.cam)
        self.persons, self.objects, self.outages, self.marks = sc.persons, sc.objects, sc.outages, sc.marks
        self.n = len(self.x)
        self.T = self.n * DT
        # Per-sample body size; who == -1 (nobody) picks the last entry.
        ps = self.persons
        self.width = np.array([q.width_m for q in ps] + [0.4])[self.who]
        self.depth = np.array([q.depth_db for q in ps] + [0.0])[self.who]
        self.height = np.array([q.height_m for q in ps] + [1.75])[self.who]
        self.by = [self._bystander() for _ in range(self.env.bystanders)]

    def _bystander(self):
        """Walks back and forth along a ring outside the square, with pauses."""
        rng = self.rng
        off = rng.uniform(*self.env.bystander_m)
        side = SIZE + 2 * off
        per = 4 * side
        s, out = rng.uniform(0, per), np.empty(self.n)
        v, k = 0.0, 0
        while k < self.n:
            m = int(rng.uniform(2, 8) / DT)
            v = rng.choice([-1, 1]) * rng.uniform(0.5, 1.2) if rng.random() < 0.7 else 0.0
            out[k:k + m] = s + v * DT * np.arange(1, min(m, self.n - k) + 1)
            s = out[min(k + m, self.n) - 1]
            k += m
        s = np.mod(out, per)
        seg, u = np.floor(s / side), np.mod(s, side)
        x = np.select([seg == 0, seg == 1, seg == 2], [u, side, side - u], 0.0) - off
        y = np.select([seg == 0, seg == 1, seg == 2], [0.0, u, side], side - u) - off
        return x, y

    def idx(self, t):
        return np.clip((np.asarray(t) / DT).astype(int), 0, self.n - 1)

    def truth(self, t):
        """True presence, zone and motion at times t (s)."""
        i = self.idx(t)
        x, y = self.x[i], self.y[i]
        inside = np.isfinite(x) & (x >= 0) & (x < SIZE) & (y >= 0) & (y < SIZE)
        zone = np.where(inside, 1 + (np.nan_to_num(x) >= 1) + 2 * (np.nan_to_num(y) < 1), 0)
        j = self.idx(np.asarray(t) - 1.0)
        speed = np.hypot(x - self.x[j], y - self.y[j])
        moving = inside & np.isfinite(speed) & (speed > 0.25)
        return inside, zone, moving


def _ar1_complex(rng, n, step, tau):
    a = math.exp(-step / max(tau, 1e-3))
    w = (rng.normal(size=n) + 1j * rng.normal(size=n)) * math.sqrt((1 - a * a) / 2)
    w[0] = (rng.normal() + 1j * rng.normal()) / math.sqrt(2)
    return lfilter([1.0], [1.0, -a], w)


def _ou(rng, n, step, tau, sigma):
    a = math.exp(-step / tau)
    w = rng.normal(0, sigma * math.sqrt(1 - a * a), n)
    w[0] = rng.normal(0, sigma)
    return lfilter([1.0], [1.0, -a], w)


def _bursts(rng, T, per_min, mean_s):
    n = rng.poisson(per_min * T / 60)
    on = rng.uniform(0, T, n)
    return [(t, t + rng.exponential(mean_s)) for t in on]


def _in_any(t, spans):
    hit = np.zeros(len(t), bool)
    for a, b in spans:
        hit |= (t >= a) & (t < b)
    return hit


class Radio:
    """Samples every link and the camera over a Timeline."""

    def __init__(self, tl: Timeline, rng):
        self.tl, self.env, self.rng = tl, tl.env, rng
        env = self.env
        self.k_lin = {lk: 10 ** ((env.k_db + rng.normal(0, 2)) / 10) for lk in LINKS}
        self.offset = {lk: rng.normal(0, env.offset_db) for lk in LINKS}
        self.chan = {lk: rng.normal(0, env.ble_chan_db, 3) for lk in LINKS}
        self.phase = {lk: rng.uniform(0, 2 * np.pi, 8) for lk in LINKS}
        step = 0.05
        self.diffuse = {lk: _ar1_complex(rng, int(tl.T / step) + 2, step, env.coherence_s) for lk in LINKS}
        nd = int(tl.T) + 2
        self.drift = {k: _ou(rng, nd, 1.0, env.drift_tau_s, env.drift_db / math.sqrt(2))
                      for k in LINKS + ["east", "west", "pi5"]}
        self.bursts = {(rx, band): _bursts(rng, tl.T, env.burst_per_min, env.burst_s)
                       for rx in ("unoq", "pi5") for band in ("wifi", "ble")}

    def level(self, link, t, chan=None):
        """True dBm (before rounding) of a link at times t."""
        tl, env = self.tl, self.env
        tx, rx = ENDS[link]
        kind = KIND[link]
        a, b = NODES[tx], NODES[rx]
        lam = LAMBDA_M[kind]
        D = math.dist(a, b)
        ref = REF_DBM["wifi"] if kind == "wifi" else REF_DBM["pi5" if tx == "pi5" else "phone"]
        base = ref - 10 * env.pl_exp * math.log10(D) + self.offset[link]
        i = tl.idx(t)
        px, py = tl.x[i], tl.y[i]
        loss = shadow_db(px, py, a, b, lam, tl.width[i], tl.depth[i], tl.height[i])
        loss = loss + shadow_db(tl.hx[i], tl.hy[i], a, b, lam, 0.1, env.hand_db)
        ph = self.phase[link]
        field = scatter_field(px, py, a, b, lam, env.scatter, ph[0])
        field = field + scatter_field(tl.hx[i], tl.hy[i], a, b, lam, 0.4 * env.scatter, ph[1])
        for j, (bx, by) in enumerate(tl.by[:4]):
            field = field + scatter_field(bx[i], by[i], a, b, lam, env.scatter, ph[2 + j])
        for o in tl.objects:
            on = (t >= o["t_on"]) & (t < o["t_off"])
            ox, oy = np.where(on, o["x"], np.nan), np.where(on, o["y"], np.nan)
            loss = loss + shadow_db(ox, oy, a, b, lam, o["width_m"], o["depth_db"])
            field = field + scatter_field(ox, oy, a, b, lam, 0.3, ph[6])
        dif = self.diffuse[link][np.clip((np.asarray(t) / 0.05).astype(int), 0, len(self.diffuse[link]) - 1)]
        E = 10 ** (-loss / 20) + field + dif / math.sqrt(self.k_lin[link])
        dbm = base + 20 * np.log10(np.maximum(np.abs(E), 1e-3))
        k = np.asarray(t, float)
        for key in (link, tx):
            if key in self.drift:
                dbm = dbm + np.interp(k, np.arange(len(self.drift[key])), self.drift[key])
        if chan is not None:
            dbm = dbm + self.chan[link][chan]
        return dbm + self.rng.normal(0, env.meas_db, len(k))

    def _silent(self, link, t):
        tx, rx = ENDS[link]
        spans = [(o["t_on"], o["t_off"]) for o in self.tl.outages
                 if o.get("link") == link or o.get("node") in (tx, rx)]
        return _in_any(t, spans)

    def readings(self):
        """{link: (t_s array, dbm int array)}."""
        env, rng, T = self.env, self.rng, self.tl.T
        out = {}
        # Wi-Fi: polls repeat the last frame heard from the Pi.
        polls = np.cumsum(np.full(int(T * env.wifi_poll_hz) + 5, 1 / env.wifi_poll_hz))
        polls = polls + rng.normal(0, env.wifi_jitter_ms / 1000, len(polls))
        polls += np.where(rng.random(len(polls)) < 0.005, rng.uniform(0.1, 0.4, len(polls)), 0)
        polls = np.sort(polls[(polls > 0) & (polls < T)])
        frames = np.cumsum(rng.exponential(1 / env.wifi_frame_hz, int(T * env.wifi_frame_hz * 1.3) + 10))
        frames = frames[frames < T]
        lost = _in_any(frames, self.bursts[("unoq", "wifi")]) & (rng.random(len(frames)) < 0.9)
        frames = frames[~lost]
        val = self.level(WIFI, frames)
        k = np.searchsorted(frames, polls, side="right") - 1
        keep = (k >= 0) & ~self._silent(WIFI, polls)
        keep &= ~(_in_any(polls, self.bursts[("unoq", "wifi")]) & (rng.random(len(polls)) < 0.3))
        out[WIFI] = (polls[keep], np.round(val[k[keep]]).astype(int))
        # BLE: one advert train per beacon, each scanner hears its own subset.
        for tx, hz, miss in (("pi5", env.pi_ble_hz, env.pi_ble_miss),
                             ("east", env.phone_hz, env.phone_miss), ("west", env.phone_hz, env.phone_miss)):
            gaps = 1 / hz + rng.uniform(0, 0.01, int(T * hz * 1.2) + 10)
            adv = np.cumsum(gaps)
            adv = adv[adv < T]
            if tx != "pi5" and env.throttle_per_min > 0:
                slow = _bursts(rng, T, env.throttle_per_min, 8.0)
                keep = ~_in_any(adv, slow) | (rng.random(len(adv)) < 1.0 / hz)
                adv = adv[keep]
            for lk in LINKS:
                if ENDS[lk][0] != tx or KIND[lk] != "ble":
                    continue
                rx = ENDS[lk][1]
                heard = rng.random(len(adv)) >= miss
                heard &= ~(_in_any(adv, self.bursts[(rx, "ble")]) & (rng.random(len(adv)) < 0.9))
                heard &= ~self._silent(lk, adv)
                ts = adv[heard]
                chan = rng.integers(0, 3, len(ts))
                out[lk] = (ts, np.round(self.level(lk, ts, chan)).astype(int))
        return out

    def labels(self):
        """Camera teacher labels: list of (t_s, label fields), and cam (t_s, state, fps)."""
        env, rng, tl = self.env, self.rng, self.tl
        frames = np.cumsum(1 / env.cam_fps + rng.normal(0, 0.01, int(tl.T * env.cam_fps) + 5))
        frames = frames[(frames > 0) & (frames < tl.T)]
        bias = rng.normal(0, env.foot_bias_m, 2)
        labels, track = [], []
        for n, t in enumerate(frames):
            i = int(t / DT)
            if tl.cam[i] != "on" or rng.random() < env.cam_miss:
                continue
            x, y = tl.x[i], tl.y[i]
            view = -env.cam_view_m, SIZE + env.cam_view_m
            seen = np.isfinite(x) and view[0] <= x <= view[1] and view[0] <= y <= view[1] \
                and rng.random() >= env.det_miss
            others = sum(1 for bx, by in tl.by if view[0] <= bx[i] <= view[1] and view[0] <= by[i] <= view[1])
            lab = {"frame": n, "mode": str(tl.mode[i]), "persons_in_frame": int(seen) + others,
                   "present": False, "zone": 0, "foot_m": None, "motion": None,
                   "conf": round(float(rng.uniform(0.6, 0.95)), 2), "clipped": False}
            if seen:
                fx, fy = np.array([x, y]) + bias + rng.normal(0, env.foot_noise_m, 2)
                edge = min(abs(x), abs(SIZE - x), abs(y), abs(SIZE - y))
                inside = 0 <= fx < SIZE and 0 <= fy < SIZE
                if edge < env.clip_m and rng.random() < 0.5:
                    lab.update(present=inside, zone=None, clipped=True)
                elif inside:
                    track.append((t, fx, fy))
                    lab.update(present=True, zone=zone_of(fx, fy), foot_m=[round(fx, 2), round(fy, 2)],
                               motion=_motion(track, t))
            labels.append((t, lab))
        cam = [(float(s), str(tl.cam[int(s / DT)])) for s in np.arange(0, tl.T, 1.0)]
        return labels, cam


def _motion(track, t):
    """Contract section 6: foot speed over 1 s > 0.25 m/s, after a 0.5 s median filter."""
    while track and track[0][0] < t - 1.6:
        track.pop(0)

    def med(at):
        pts = [(x, y) for s, x, y in track if at - 0.5 <= s <= at]
        return np.median(pts, axis=0) if pts else None
    now, then = med(t), med(t - 1.0)
    if now is None or then is None:
        return "still"
    return "moving" if float(np.hypot(*(now - then))) > 0.25 else "still"


def messages(tl: Timeline, seed: int = 0, src: str = "sim"):
    """All bus messages for a timeline, sorted by recv_t (board ms)."""
    rng = np.random.default_rng(seed + 7919)
    radio = Radio(tl, rng)
    seq = {"wifi": 0, "unoq": 0, "pi5": 0, "cam": 0}
    pi_clock = rng.normal(0, 40)   # the Pi's clock is not the board's; windows use recv_t only
    out = []

    def env_(producer, t_ms, recv_ms, body):
        seq[producer] += 1
        return {"v": 2, "type": body.pop("type"), "t": int(t_ms), "seq": seq[producer], "src": src,
                **body, "recv_t": int(recv_ms)}

    for link, (ts, dbm) in radio.readings().items():
        tx, rx = ENDS[link]
        producer = "wifi" if KIND[link] == "wifi" else rx
        lat = rng.uniform(1, 6, len(ts)) if rx == "pi5" else rng.uniform(0.5, 3, len(ts))
        for t, d, la in zip(ts, dbm, lat):
            ms = T0_MS + t * 1000
            out.append(env_(producer, ms + (pi_clock if rx == "pi5" else 0), ms + la,
                            {"type": "rssi", "link": link, "kind": KIND[link], "tx": tx, "rx": rx,
                             "dbm": int(d)}))
    labels, cams = radio.labels()
    lat = tl.env.cam_latency_ms
    for t, lab in labels:
        ms = T0_MS + t * 1000
        out.append(env_("cam", ms, ms + max(5.0, rng.normal(lat, 20)), {"type": "label", **lab}))
    for t, state in cams:
        ms = T0_MS + t * 1000
        out.append(env_("cam", ms, ms + 2, {"type": "cam", "state": state,
                                            "fps": tl.env.cam_fps if state == "on" else 0.0}))
    out.sort(key=lambda m: m["recv_t"])
    return out


def draw_env(rng, ranges: dict, fixed: dict = None) -> Env:
    """An Env with each field in `ranges` drawn uniformly, then `fixed` applied."""
    env = Env()
    for k, (lo, hi) in ranges.items():
        v = rng.uniform(lo, hi)
        setattr(env, k, int(round(v)) if isinstance(getattr(env, k), int) else float(v))
    for k, v in (fixed or {}).items():
        setattr(env, k, v)
    return env

