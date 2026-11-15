"""Sim paths as bus messages (v2, with recv_t as the bus would stamp it), for tests."""
import json

from sim import fake, wire

T0_MS = 1_763_149_500_000


def sim_to_v2(name, seed=0, mode=None, meta=None, t0=T0_MS, noise_db=1.0):
    """Run a sim path. mode overrides the path's label_mode (person | object | off)."""
    path = dict(fake.load_path(name))
    if mode:
        path["label_mode"] = mode
    if meta:
        path["meta"] = meta
    encode = wire.encoder(t0)
    out = []
    for ev in fake.simulate(path, seed=seed, noise_db=noise_db):
        msg = json.loads(encode(ev))
        msg["recv_t"] = msg["t"]
        out.append(msg)
    return out


def errors(msg):
    """Contract errors in one state or event from these tests, [] if it is fine.

    The schemas in contracts/ describe the layout in radio/nodes.json; this folder's tests run
    on their own square (conftest.py). When the two differ (the room moved on) there is nothing
    to compare, and this returns []: test_layout.py checks the schemas on the repo's own layout.
    """
    from pathlib import Path

    from contracts import check
    here = Path(__file__).resolve().parent
    own = json.loads((here / "square_nodes.json").read_text(encoding="utf-8"))
    repo = json.loads((here.parent.parent / "radio" / "nodes.json").read_text(encoding="utf-8"))
    same = [link["id"] for link in own["links"]] == [link["id"] for link in repo["links"]] \
        and len(own["zones"]) == len(repo["zones"])
    return check.errors(msg) if same else []
