"""Sim paths as bus messages (v2, with recv_t as the bus would stamp it), for tests."""
import json

from sim import fake, wire

T0_MS = 1_763_149_500_000


def sim_to_v2(name, seed=0, mode=None):
    """Run a sim path. mode overrides the path's label_mode (person | object | off)."""
    path = dict(fake.load_path(name))
    if mode:
        path["label_mode"] = mode
    encode = wire.encoder(T0_MS)
    out = []
    for ev in fake.simulate(path, seed=seed):
        msg = json.loads(encode(ev))
        msg["recv_t"] = msg["t"]
        out.append(msg)
    return out
