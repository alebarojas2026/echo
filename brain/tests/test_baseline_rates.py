"""A new baseline measures the rates again."""
from brain.core import Brain
from brain.tests.simdata import T0_MS
from brain.tests.test_core import cmd

def test_a_new_baseline_finishes_when_the_beacons_now_send_far_slower_than_before():
    """Yesterday's baseline measured 30 readings a second; today's beacons send 10. The old
    expected rate must not call every link stale and hold the new baseline off for ever."""
    import json
    from sim import fake, wire

    def feed(brain, rate, t0, seconds=30):
        path = dict(fake.load_path("empty_room"), duration_s=seconds)
        encode, t = wire.encoder(t0), t0
        for ev in fake.simulate(path, rate=rate, seed=3):
            m = json.loads(encode(ev))
            m["recv_t"] = t = m["t"]
            brain.on_message(m)
            if m["type"] == "cam":
                brain.state()                      # the live loop takes state all the time
        return t + 100

    brain = Brain()
    brain.on_cmd(cmd("baseline"))
    t = feed(brain, 30.0, T0_MS)
    assert brain.expected_hz["east>unoq:ble"] > 25 and brain.capture is None
    t = feed(brain, 10.0, t, seconds=8)            # slower beacons: stale against the old rate
    assert brain.state()["health"]["status"] != "ok"
    brain.on_cmd(cmd("baseline"))
    feed(brain, 10.0, t, seconds=35)
    assert brain.capture is None, "the new baseline never finished"
    assert 8 < brain.expected_hz["east>unoq:ble"] < 12
    assert brain.state()["health"]["status"] == "ok"
