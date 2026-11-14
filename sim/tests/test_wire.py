"""The lines on the wire match CONTRACTS.md v2, sections 1 and 4."""
import json

from sim import fake
from sim.wire import as_replay, encoder, time_of

ENVELOPE = ["v", "type", "t", "seq", "src"]
FIELDS = {  # copied from the examples in CONTRACTS.md section 4
    "rssi": ["link", "kind", "tx", "rx", "dbm"],
    "label": ["frame", "mode", "persons_in_frame", "present", "zone", "foot_m", "motion", "conf", "clipped"],
    "cam": ["state", "fps"],
    "meta": ["session", "purpose", "walker"],
}


def lines(start_ms=1763149500000):
    encode = encoder(start_ms)
    walk = {"duration_s": 2, "person": [{"t": 0, "x": 0.5, "y": 0.5}, {"t": 1, "x": None}]}
    return [(e, encode(e)) for e in fake.simulate(walk)]


def test_every_message_has_the_envelope_and_exactly_the_contract_fields():
    seen = set()
    for _, line in lines():
        msg = json.loads(line)
        assert "\n" not in line
        assert list(msg)[:5] == ENVELOPE
        assert (msg["v"], msg["src"]) == (2, "sim")
        assert sorted(list(msg)[5:]) == sorted(FIELDS[msg["type"]])
        seen.add(msg["type"])
    assert seen == set(FIELDS)


def test_t_is_epoch_ms_and_seq_counts_up_by_one():
    msgs = [json.loads(line) for _, line in lines()]
    assert all(isinstance(m["t"], int) for m in msgs)
    assert msgs[0]["t"] == 1763149500000
    assert [m["seq"] for m in msgs] == list(range(1, len(msgs) + 1))
    for (event, _), msg in zip(lines(), msgs):
        assert msg["t"] - 1763149500000 == round(event["t"] * 1000)


def test_field_types():
    for _, line in lines():
        m = json.loads(line)
        if m["type"] == "rssi":
            assert isinstance(m["dbm"], int) and m["kind"] in ("wifi", "ble")
        if m["type"] == "label":
            assert m["zone"] in (0, 1, 2, 3, 4) and m["motion"] in ("moving", "still", None)
            assert m["foot_m"] is None or len(m["foot_m"]) == 2


def test_each_encoder_is_its_own_producer():
    a, b = encoder(), encoder(src="live")
    event = {"type": "cam", "t": 0.0, "state": "on", "fps": 7.5}
    assert [json.loads(a(event))["seq"] for _ in range(3)] == [1, 2, 3]
    assert json.loads(b(event))["seq"] == 1 and json.loads(b(event))["src"] == "live"


def test_time_of_prefers_recv_t():
    assert time_of('{"t":1763149512120}') == 1763149512.12
    assert time_of('{"t":1763149512120,"recv_t":1763149512500}') == 1763149512.5


def test_as_replay_changes_only_src_and_recv_t():
    line = '{"v":2,"type":"cam","t":5,"seq":7,"src":"live","state":"on","fps":9.6,"recv_t":9}'
    assert json.loads(as_replay(line)) == {
        "v": 2, "type": "cam", "t": 5, "seq": 7, "src": "replay", "state": "on", "fps": 9.6}
