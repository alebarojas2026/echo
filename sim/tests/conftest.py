"""Layouts for the sim's tests.

The fake feed and the fake brain take their layout from radio/nodes.json, and that file is
moving from the 2 x 2 m square to the desk strip. A test that checks a rule with numbers for one
layout pins that layout (the `square` and `strip` fixtures); a test that plays the path files
runs on both (`each_layout`), so every path is checked on the square and on the strip whichever
file is in radio/nodes.json. layouts/square.json is main's file before the desk, and
layouts/strip.json the desk layout in contract PR #415.
"""
from pathlib import Path

import pytest

from narrator import narrate
from sim import fake, layout, state

LAYOUTS = Path(__file__).parent / "layouts"


def load(name: str) -> layout.Layout:
    return layout.load(LAYOUTS / f"{name}.json")


def pin(monkeypatch, name: str) -> layout.Layout:
    """Make the fake feed, the fake brain and the narrator's zone words use this layout until
    the test ends (monkeypatch puts the file's layout back)."""
    lay = load(name)
    lay.name = name
    for attr, value in {"LAYOUT": lay, "SIZE": lay.size_m[0], "NODES": dict(lay.nodes), "LINKS": list(lay.links),
                        "ROUTER_SPOTS": dict(lay.router_spots), "PERSON_WIDTH_M": lay.width_m,
                        "PERSON_BODY_M": lay.body_m}.items():
        monkeypatch.setattr(fake, attr, value)
    for attr, value in {"LAYOUT": lay, "STILL_ALERT_S": dict(lay.zones), "GRID": lay.grid, "BUMP_M": lay.bump_m}.items():
        monkeypatch.setattr(state, attr, value)
    monkeypatch.setattr(narrate, "ZONES", narrate.load_zones(LAYOUTS / f"{name}.json"))   # the zone words
    return lay


@pytest.fixture
def square(monkeypatch):
    return pin(monkeypatch, "square")


@pytest.fixture
def strip(monkeypatch):
    return pin(monkeypatch, "strip")


@pytest.fixture(params=["square", "strip"])
def each_layout(request, monkeypatch):
    return pin(monkeypatch, request.param)


def schema_fits(lay: layout.Layout) -> bool:
    """The schema in contracts/ lists the links of the layout in radio/nodes.json, so a pinned
    layout's messages are checked against it only when that is the same layout."""
    return lay.links == layout.load().links
