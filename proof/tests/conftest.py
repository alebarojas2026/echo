import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def square(monkeypatch):
    """Pin the 2 x 2 m square for a test that checks square-specific numbers, so it passes
    whichever layout radio/nodes.json (or RADIO_SIGHT_NODES) holds."""
    from proof import layout, score
    path = FIXTURES / "square-nodes.json"
    monkeypatch.setenv("RADIO_SIGHT_NODES", str(path))
    monkeypatch.setattr(score, "LAYOUT", layout.load(path))
    return layout.load(path)


@pytest.fixture
def gate(monkeypatch):
    """Pin the gate layout (one spot, three devices, six links): this folder's copy of radio/layouts/gate.json."""
    from proof import layout, score
    path = FIXTURES / "gate-nodes.json"
    monkeypatch.setenv("RADIO_SIGHT_NODES", str(path))
    monkeypatch.setattr(score, "LAYOUT", layout.load(path))
    return layout.load(path)
