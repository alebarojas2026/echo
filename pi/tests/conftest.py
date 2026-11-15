"""pi/'s tests are written against the desk layout, like radio/'s: they run on radio/layouts/desk.json
whatever radio/nodes.json holds today (see radio/tests/conftest.py)."""
import pytest

from radio.tests.conftest import DESK, _read_from

_read_from(DESK)


@pytest.fixture(scope="package", autouse=True)
def desk_layout():
    yield
    _read_from(None)
