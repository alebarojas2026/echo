"""The brain's tests run on a layout of their own: the 2 x 2 m square in square_nodes.json.

They check rules (windows, health, the x-ray, alerts, training), and their numbers (the tray at
T1, a walk through four zones) are drawn on that square. radio/nodes.json is free to change
with the room; brain/tests/test_layout.py is where other layouts, and the repo's own file,
are tried.

Two things are pinned for as long as this folder's tests run, and put back after:
- RADIO_SIGHT_NODES, so brain.layout (and with it Brain()'s default) reads square_nodes.json.
  It is set here, before any test module imports the brain.
- the sim's fake feed (sim.fake), which otherwise follows radio/nodes.json, and its paths,
  which are read from brain/tests/paths.
Run this folder as its own pytest run (as CI and the merge gate do), or first in one: when
its tests are done the brain's modules are loaded again from radio/nodes.json, so whatever runs
after them in the same run (sim, proof) gets the real layout. The other way round can't work:
if something has already imported the brain on another layout, this stops with a message.
"""
import importlib
import json
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SQUARE = HERE / "square_nodes.json"
BRAIN_MODULES = ("brain.layout", "brain.features", "brain.health", "brain.xray", "brain.train", "brain.alert",
                 "brain.lesson", "brain.core", "brain.main", "brain.tune_checkin")   # in import order


def _links(path):
    return [link["id"] for link in json.loads(Path(path).read_text(encoding="utf-8"))["links"]]


_loaded = sys.modules.get("brain.layout")
if _loaded is not None and Path(_loaded.NODES_JSON) != SQUARE and _links(_loaded.NODES_JSON) != _links(SQUARE):
    raise pytest.UsageError(
        "brain/tests pin their own layout (brain/tests/square_nodes.json), but the brain was already imported "
        "on radio/nodes.json's by an earlier folder in this run. Run brain/ by itself or put it first: "
        "python -m pytest brain")
os.environ["RADIO_SIGHT_NODES"] = str(SQUARE)


@pytest.fixture(scope="package", autouse=True)
def square_layout():
    from sim import fake
    from sim.layout import Layout

    lay = Layout(json.loads(SQUARE.read_text(encoding="utf-8")))
    saved = (fake.LAYOUT, fake.SIZE, dict(fake.NODES), list(fake.LINKS), dict(fake.ROUTER_SPOTS), fake.load_path)

    def put(layout, size, nodes, links, spots, load_path):
        fake.LAYOUT, fake.SIZE, fake.load_path = layout, size, load_path
        fake.NODES.clear(), fake.NODES.update(nodes)            # in place: they are default arguments too
        fake.LINKS[:] = links
        fake.ROUTER_SPOTS.clear(), fake.ROUTER_SPOTS.update(spots)

    def load_path(name_or_file):
        own = HERE / "paths" / f"{name_or_file}.json"
        return json.loads(own.read_text(encoding="utf-8")) if own.exists() else saved[5](name_or_file)

    put(lay, lay.size_m[0], lay.nodes, lay.links, lay.router_spots, load_path)
    yield
    put(*saved)
    os.environ.pop("RADIO_SIGHT_NODES", None)
    for name in BRAIN_MODULES:               # back to radio/nodes.json for whatever runs next
        if name in sys.modules:
            importlib.reload(sys.modules[name])
