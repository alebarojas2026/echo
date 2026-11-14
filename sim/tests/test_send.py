import json
import socket
import time

import pytest

from sim import fake, send
from sim.wire import encoder


@pytest.fixture
def bus():
    """A stand-in for the bus: a UDP socket on a free local port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(1.0)
    yield sock
    sock.close()


def receive(sock, n):
    return [json.loads(sock.recvfrom(65535)[0]) for _ in range(n)]


def short_path(tmp_path, seconds=1):
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"name": "p", "duration_s": seconds, "person": [{"t": 0, "x": 0.5, "y": 0.5}]}))
    return str(f)


def port(sock):
    return str(sock.getsockname()[1])


def test_default_target_is_the_bus_port_from_the_contract():
    assert send.BUS == ("127.0.0.1", 5600)


def test_sends_one_contract_message_per_datagram(tmp_path, bus):
    before = int(time.time() * 1000)
    sent = send.main([short_path(tmp_path), "--port", port(bus), "--speed", "50"])
    msgs = receive(bus, sent)
    assert sent == 1 + 6 * 15 + 8 + 1  # meta, rssi, labels, cam
    assert [m["seq"] for m in msgs] == list(range(1, sent + 1))
    assert {m["type"] for m in msgs} == {"meta", "rssi", "label", "cam"}
    assert all(m["v"] == 2 and m["src"] == "sim" for m in msgs)
    assert before <= msgs[0]["t"] <= before + 2000  # stamped with the real clock, epoch ms
    assert msgs[-1]["t"] - msgs[0]["t"] == 933


def test_sends_at_real_speed(tmp_path, bus):
    start = time.monotonic()
    send.main([short_path(tmp_path), "--port", port(bus)])
    assert 0.8 <= time.monotonic() - start <= 1.3


def test_recording_is_sent_as_replay(tmp_path, bus):
    encode = encoder(1763149500000, src="live")
    lines = [encode(e) for e in fake.simulate(fake.load_path("empty_room")) if e["t"] < 0.3]
    f = tmp_path / "s.jsonl"
    f.write_text("\n".join(lines) + "\n")
    sent = send.main([str(f), "--port", port(bus), "--speed", "50"])
    msgs = receive(bus, sent)
    assert sent == len(lines)
    assert {m["src"] for m in msgs} == {"replay"}
    assert [m["t"] for m in msgs] == [json.loads(l)["t"] for l in lines]


def test_nobody_listening_is_not_an_error(tmp_path):
    assert send.main([short_path(tmp_path), "--port", "9", "--speed", "200"]) > 0


def test_recording_with_several_producers_goes_out_as_one(tmp_path, bus):
    radio, camera = encoder(1763149500000, src="live"), encoder(1763149500000, src="live")
    events = [e for e in fake.simulate(fake.load_path("zone_tour")) if e["t"] < 0.4]
    lines = [(camera if e["type"] in ("label", "cam") else radio)(e) for e in events]
    recorded = [json.loads(l)["seq"] for l in lines]
    assert recorded != sorted(recorded)  # two counters interleaved, as the bus records them
    f = tmp_path / "s.jsonl"
    f.write_text("\n".join(lines) + "\n")
    sent = send.main([str(f), "--port", port(bus), "--speed", "50"])
    msgs = receive(bus, sent)
    assert [m["seq"] for m in msgs] == list(range(1, len(lines) + 1))
    for got, line in zip(msgs, lines):  # nothing else in the line changes
        want = {**json.loads(line), "src": "replay", "seq": got["seq"]}
        assert got == want


def test_replay_seq_keeps_counting_across_loops(tmp_path, bus, monkeypatch):
    encode = encoder(1763149500000, src="live")
    f = tmp_path / "s.jsonl"
    f.write_text("\n".join(encode({"type": "cam", "t": i / 10, "state": "on", "fps": 7.5}) for i in range(3)) + "\n")
    rounds = iter([None, None, KeyboardInterrupt])

    def pace_twice_then_stop(timed, **kw):
        if next(rounds) is KeyboardInterrupt:
            raise KeyboardInterrupt
        return fake.pace(timed, **kw)

    monkeypatch.setattr(send, "pace", pace_twice_then_stop)
    sent = send.main([str(f), "--port", port(bus), "--speed", "50", "--loop"])
    assert [m["seq"] for m in receive(bus, sent)] == [1, 2, 3, 4, 5, 6]
