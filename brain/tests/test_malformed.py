"""One malformed message must not stop the decisions (issue #520)."""
import pytest

from brain import features as F
from brain.core import Brain

T = 1_000_000


def rssi(t, link="east>pi5:ble", **more):
    return {"v": 2, "type": "rssi", "t": t, "seq": 1, "src": "sim", "link": link, "kind": "ble",
            "tx": "east", "rx": "pi5", "dbm": -55, "recv_t": t, **more}


def label(t, **more):
    return {"v": 2, "type": "label", "t": t, "seq": 1, "src": "sim", "recv_t": t, "mode": "person",
            "persons_in_frame": 1, "present": True, "zone": 2, "motion": "still", "clipped": False, **more}


@pytest.mark.parametrize("bad", [rssi(T + 2100, link=["a"]), rssi(T + 2100, link={"a": 1}), rssi(T + 2100, link=None),
                                 label(T + 2100, zone=[1]), label(T + 2100, zone="2"),
                                 label(T + 2100, persons_in_frame=[1])])
def test_windows_keep_closing_after_one_malformed_message(bad):
    brain = Brain()
    brain._set_baseline({link: -50.0 for link in brain.links}, {link: 15.0 for link in brain.links})
    for i in range(30):
        brain.on_message(rssi(T + i * 70))
    brain.on_message(bad)                              # the bus forwards whatever it was sent
    for i in range(600):                               # 42 s of good readings: none may raise
        brain.on_message(rssi(T + 2200 + i * 70))
    assert brain.window["end"] > T + 40_000            # and the windows kept moving


def test_a_window_that_cannot_be_closed_is_skipped_not_retried():
    w = F.Windower({"east>pi5:ble": -50.0})
    w.push(rssi(T))
    w._labels.append((T + 10, {"zone": [1], "present": True}))   # something bad got in anyway
    with pytest.raises(TypeError):
        w.push(rssi(T + 1500))
    for i in range(40):                                # the next readings are fine again once it has aged out
        w.push(rssi(T + 1600 + i * 100))
    assert w.push(rssi(T + 6000))                      # windows close again
