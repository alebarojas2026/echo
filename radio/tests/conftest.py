"""These tests are written against the desk layout (east and west beacons, the hall beacons), so
they run on radio/layouts/desk.json whatever radio/nodes.json holds today. test_layouts.py and
test_gate_layout.py are where the other layout files are tried.

radio.nodes is read once, with RADIO_SIGHT_NODES naming the desk file, before any test module
imports it; the variable is put back at once, so nothing started from a test inherits it. When
this folder's tests are done, radio.nodes and whatever copied from it are loaded again from
radio/nodes.json for the folders that run after.
"""
import importlib
import os
import sys
from pathlib import Path

import pytest

DESK = Path(__file__).resolve().parents[1] / "layouts" / "desk.json"
ACTIVE = DESK.parents[1] / "nodes.json"


def _same(a, b):
    return Path(a).read_bytes() == Path(b).read_bytes()


def _read_from(path):
    """radio.nodes read from `path` (None: radio/nodes.json). Loaded modules that copied from it (radio.*, pi.*)
    are loaded again too, twice over so the order they import each other in doesn't matter."""
    saved = os.environ.get("RADIO_SIGHT_NODES")
    os.environ["RADIO_SIGHT_NODES"] = str(path or ACTIVE)
    try:
        loaded = sys.modules.get("radio.nodes")
        if loaded is None:
            importlib.import_module("radio.nodes")
        elif not _same(loaded.PATH, path or ACTIVE):
            importlib.reload(loaded)
            copiers = [m for name, m in sorted(sys.modules.items())
                       if name.startswith(("radio.", "pi.")) and ".tests" not in name
                       and name not in ("radio.nodes", "radio.use_layout") and m is not None]
            for module in copiers + copiers:
                importlib.reload(module)
    finally:
        if saved is None:
            os.environ.pop("RADIO_SIGHT_NODES", None)
        else:
            os.environ["RADIO_SIGHT_NODES"] = saved


_read_from(DESK)


@pytest.fixture(scope="package", autouse=True)
def desk_layout():
    yield
    _read_from(None)
