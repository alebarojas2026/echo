"""The narrator reads its zones from radio/nodes.json when it is imported. These tests check
sentences word for word, so they pin one layout (the 2 x 2 m square) whatever the repo's file says."""
import pytest

from narrator import narrate as n

SQUARE = {1: ("Bed", 60), 2: ("Chair", None), 3: ("Hall", None), 4: ("Bathroom", 10)}


@pytest.fixture(autouse=True)
def square_zones():
    saved = dict(n.ZONES)
    n.set_zones(SQUARE)
    yield
    n.set_zones(saved)
