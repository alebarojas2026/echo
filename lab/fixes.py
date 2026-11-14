"""Candidate fixes, replayed on the same recorded live stream. SIMULATED, dev only.

Ghost objects and stale advice after the tray is removed (seen on main once the
X-ray steadiness moved to 0.5 s means):
  - clamp: a link's static part follows the link back down (_ClampXray);
  - gate: advise only while pi5>unoq:wifi currently drops >= 3 dB.
"""
from __future__ import annotations

import numpy as np

from advisor.advise import advise
from brain import xray as X
from lab import rf
from lab.run import NODES_DOC, _in


class _ClampXray(X.Xray):
    """Candidate fix: a link's static part never exceeds what it drops right now."""

    def link_levels(self, now_s, kind=None):
        people, static, fresh = super().link_levels(now_s, kind)
        for k, link in enumerate(self.links):
            t, v = np.array(self._hist[link]).reshape(-1, 2).T
            d = X.current_drop(t, v, now_s) if t.size else None
            if d is not None and d < self.static_link_db[k]:
                self.static_link_db[k] = max(d, 0.0)
        return people, np.maximum(self.static_link_db, 0.0), fresh


XRAYFIX = [{"fix": "none"}, {"fix": "clamp"}, {"fix": "gate"}, {"fix": "clamp+gate"}]


def replay_xrayfix(res, plan, variants=XRAYFIX):
    """Ghost objects and stale advice after the tray goes: candidate fixes on the same stream.

    clamp: the X-ray's static part follows a link back down (_ClampXray).
    gate: advice only while pi5>unoq:wifi currently drops >= 3 dB.
    """
    T0 = rf.T0_MS
    brain, sp = res["brain"], plan["spans"]
    t_on, t_off = plan["t_tray"], sp["tray_still"][0][1] + 1.0
    rows = []
    for v in variants:
        xr = (_ClampXray if "clamp" in v["fix"] else X.Xray).from_nodes(NODES_DOC)
        i, rs = 0, res["live_rssi"]
        found, ghost_s, adv_tray, adv_ghost_s, extra = False, 0.0, None, 0.0, False
        for x in res["ticks"]:
            t = x[0]
            while i < len(rs) and rs[i]["recv_t"] <= t:
                if rs[i]["link"] in brain.base:
                    xr.add(rs[i]["link"], rs[i]["recv_t"], brain.base[rs[i]["link"]] - rs[i]["dbm"])
                i += 1
            out = xr.update(t, x[2] if x[1] is not None else None)
            s = (t - T0) / 1000
            on = t_on <= s < t_off
            a = advise(out["xray"], [], NODES_DOC, out["objects"]) if out["objects"] else None
            if a and "gate" in v["fix"]:
                tw, vw = np.array(xr._hist["pi5>unoq:wifi"]).reshape(-1, 2).T
                d = X.current_drop(tw, vw, t / 1000) if tw.size else None
                a = a if d is not None and d >= 3.0 else None
            if on:
                found |= bool(out["objects"])
                extra |= _in(s, sp["tray_still"]) and len(out["objects"]) > 1
                adv_tray = adv_tray or (a["to_spot"] if a else None)
            else:
                ghost_s += 0.1 * bool(out["objects"])
                adv_ghost_s += 0.1 * bool(a)
        rows.append(dict(v, detected=found, ghost_s=round(ghost_s, 1), advice=adv_tray,
                         advice_ghost_s=round(adv_ghost_s, 1), extra_object=extra))
    return rows
