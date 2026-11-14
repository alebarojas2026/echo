import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from bus.core import Bus, open_sockets, serve

REPO = Path(__file__).resolve().parents[2]
A = ("127.0.0.1", 40001)
B = ("127.0.0.1", 40002)


def msg(seq, type_="rssi", **extra):
    m = {"v": 2, "type": type_, "t": 1763149512000 + seq, "seq": seq, "src": "live"}
    if type_ == "rssi":
        m.update(link="east>pi5:ble", kind="ble", tx="east", rx="pi5", dbm=-61)
    m.update(extra)
    return json.dumps(m).encode()


def cmd(name, **args):
    return json.dumps({"v": 2, "type": "cmd", "cmd": name, "args": args}).encode()


@pytest.fixture
def bus(tmp_path):
    sent = []
    clock = iter(range(1000, 10**6))
    b = Bus(sessions=tmp_path, send=sent.append, clock=lambda: next(clock))
    b.sent = sent
    yield b
    b.close()


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_adds_recv_t_and_forwards(bus):
    out = bus.handle(msg(1), A)
    assert out["recv_t"] == 1000
    forwarded = json.loads(bus.sent[0])
    assert forwarded["recv_t"] == 1000
    assert forwarded["link"] == "east>pi5:ble" and forwarded["seq"] == 1


def test_recv_t_overwrites_a_stale_one(bus):
    bus.handle(msg(1, recv_t=5), A)
    assert json.loads(bus.sent[0])["recv_t"] == 1000


def test_counts_seq_gaps_per_producer(bus):
    for seq in (1, 2, 5, 6):        # 3 and 4 lost
        bus.handle(msg(seq), A)
    for seq in (10, 11, 12):        # nothing lost
        bus.handle(msg(seq, "label"), B)
    a, b = bus.producers["127.0.0.1:40001"], bus.producers["127.0.0.1:40002"]
    assert (a.received, a.lost) == (4, 2)
    assert (b.received, b.lost, b.type) == (3, 0, "label")
    assert bus.lost() == 2


def test_restart_is_not_a_loss(bus):
    for seq in (7, 8, 1, 2):
        bus.handle(msg(seq), A)
    p = bus.producers["127.0.0.1:40001"]
    assert (p.lost, p.restarts) == (0, 1)


def test_message_without_seq_is_still_forwarded(bus):
    bus.handle(json.dumps({"v": 2, "type": "cam", "state": "on"}).encode(), A)
    assert len(bus.sent) == 1 and bus.lost() == 0


@pytest.mark.parametrize("data", [b"not json", b"[1,2]", b'{"v":2}', b'{"v":1,"type":"rssi"}',
                                  b"\xff\xfe"])
def test_drops_anything_off_contract(bus, data):
    assert bus.handle(data, A) is None
    assert bus.sent == [] and bus.bad == 1


def test_records_between_start_and_stop(bus, tmp_path):
    bus.handle(msg(1), A)                                   # before: not recorded
    bus.handle(cmd("record_start", session="s12", purpose="heldout", walker="w3"), B)
    bus.handle(msg(2), A)
    bus.handle(msg(1, "label", zone=4), B)
    bus.handle(cmd("record_stop"), B)
    bus.handle(msg(3), A)                                   # after: not recorded

    got = lines(tmp_path / "s12.jsonl")
    assert [m["type"] for m in got] == ["meta", "rssi", "label"]
    meta = got[0]
    assert (meta["v"], meta["session"], meta["purpose"], meta["walker"]) == (2, "s12", "heldout", "w3")
    assert all("recv_t" in m for m in got)
    assert got[1]["seq"] == 2 and got[2]["zone"] == 4


def test_meta_is_forwarded_but_cmds_are_not(bus):
    bus.handle(cmd("record_start", session="s1", purpose="train", walker=None), B)
    bus.handle(cmd("label_mode", mode="person"), B)
    bus.handle(cmd("record_stop"), B)
    assert [json.loads(d)["type"] for d in bus.sent] == ["meta"]


def test_other_cmds_are_kept_in_the_session(bus, tmp_path):
    bus.handle(cmd("record_start", session="crowd1", purpose="crowd", walker=None), B)
    bus.handle(cmd("truth", zone=2), B)
    bus.handle(cmd("record_stop"), B)
    got = lines(tmp_path / "crowd1.jsonl")
    assert got[1]["cmd"] == "truth" and got[1]["args"] == {"zone": 2}


def test_new_record_start_switches_files(bus, tmp_path):
    bus.handle(cmd("record_start", session="s1", purpose="train", walker="w1"), B)
    bus.handle(msg(1), A)
    bus.handle(cmd("record_start", session="s2", purpose="train", walker="w2"), B)
    bus.handle(msg(2), A)
    bus.handle(cmd("record_stop"), B)
    assert [m["type"] for m in lines(tmp_path / "s1.jsonl")] == ["meta", "rssi"]
    assert [m["seq"] for m in lines(tmp_path / "s2.jsonl")][1:] == [2]


def test_same_session_appends(bus, tmp_path):
    for seq in (1, 2):
        bus.handle(cmd("record_start", session="s5", purpose="demo", walker=None), B)
        bus.handle(msg(seq), A)
        bus.handle(cmd("record_stop"), B)
    assert [m["type"] for m in lines(tmp_path / "s5.jsonl")] == ["meta", "rssi"] * 2


@pytest.mark.parametrize("session", ["../evil", "a/b", "", None, 7, "x" * 65, ".hidden"])
def test_bad_session_ids_record_nothing(bus, tmp_path, session):
    bus.handle(cmd("record_start", session=session, purpose="train", walker=None), B)
    bus.handle(msg(1), A)
    assert not bus.recorder.recording
    assert list(tmp_path.iterdir()) == []
    assert not (tmp_path.parent / "evil.jsonl").exists()


def test_record_stop_without_start_is_harmless(bus):
    bus.handle(cmd("record_stop"), B)
    assert not bus.recorder.recording


def test_report_lists_each_producer(bus):
    bus.handle(msg(1), A)
    bus.handle(msg(3), A)
    bus.handle(b"junk", B)
    report = bus.report()
    assert report[0] == "127.0.0.1:40001 (rssi, live): 2 received, 1 lost, 0 restarts"
    assert report[-1] == "1 dropped (not contract v2)"


def udp_listener():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    s.settimeout(3)
    return s


def test_over_real_sockets(tmp_path):
    brain = udp_listener()
    rx, tx, send = open_sockets("127.0.0.1", 0, brain.getsockname())
    bus = Bus(sessions=tmp_path, send=send)
    stop = threading.Event()
    worker = threading.Thread(target=serve, args=(bus, rx, stop), daemon=True)
    worker.start()
    producer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    to = ("127.0.0.1", rx.getsockname()[1])
    try:
        producer.sendto(cmd("record_start", session="live1", purpose="demo", walker=None), to)
        assert json.loads(brain.recv(65535))["type"] == "meta"
        before = int(time.time() * 1000)
        for seq in (1, 2, 4):
            producer.sendto(msg(seq), to)
        got = [json.loads(brain.recv(65535)) for _ in range(3)]
        producer.sendto(cmd("record_stop"), to)
        deadline = time.time() + 3
        while bus.recorder.recording and time.time() < deadline:
            time.sleep(0.01)
    finally:
        stop.set()
        worker.join(2)
        for s in (producer, brain, rx, tx):
            s.close()
    assert [m["seq"] for m in got] == [1, 2, 4]
    assert all(before <= m["recv_t"] <= before + 3000 for m in got)
    assert bus.lost() == 1
    assert [m["type"] for m in lines(tmp_path / "live1.jsonl")] == ["meta", "rssi", "rssi", "rssi"]


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_python_dash_m_bus_runs(tmp_path):
    brain = udp_listener()
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "bus", "--host", "127.0.0.1", "--port", str(port),
         "--forward", f"127.0.0.1:{brain.getsockname()[1]}", "--sessions", str(tmp_path)],
        cwd=REPO, stderr=subprocess.PIPE, text=True)
    producer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        assert "listening on" in proc.stderr.readline()
        producer.sendto(msg(1), ("127.0.0.1", port))
        assert "recv_t" in json.loads(brain.recv(65535))
    finally:
        proc.terminate()
        proc.wait(5)
        producer.close()
        brain.close()


def test_a_new_bus_carries_on_with_the_open_recording(bus, tmp_path):
    bus.handle(cmd("record_start", session="held1", purpose="heldout", walker="w1"), B)
    bus.handle(msg(1), A)
    bus.close()                                         # systemd stops or restarts the bus
    again = Bus(sessions=tmp_path, send=lambda data: None)
    assert again.recorder.session == "held1"
    again.handle(msg(2), A)
    again.handle(cmd("record_stop"), B)
    assert [(m["type"], m.get("seq")) for m in lines(tmp_path / "held1.jsonl")] == \
        [("meta", 1), ("rssi", 1), ("rssi", 2)]       # one meta line: it just carries on
    assert not (tmp_path / ".open").exists()
    assert not Bus(sessions=tmp_path).recorder.recording


def test_record_stop_ends_it_for_the_next_bus_too(bus, tmp_path):
    bus.handle(cmd("record_start", session="s1", purpose="train", walker=None), B)
    bus.handle(cmd("record_stop"), B)
    assert not Bus(sessions=tmp_path).recorder.recording


def test_a_stale_or_bad_mark_is_dropped(bus, tmp_path):
    bus.handle(cmd("record_start", session="old1", purpose="train", walker=None), B)
    bus.close()
    old = time.time() - 3600                            # the bus was off for an hour
    os.utime(tmp_path / "old1.jsonl", (old, old))
    assert not Bus(sessions=tmp_path).recorder.recording
    assert not (tmp_path / ".open").exists()
    (tmp_path / ".open").write_text(json.dumps({"session": "../evil"}))
    assert not Bus(sessions=tmp_path).recorder.recording
    (tmp_path / ".open").write_text("not json")
    assert not Bus(sessions=tmp_path).recorder.recording


def test_a_killed_bus_process_loses_nothing_from_the_recording(tmp_path):
    port = free_port()
    argv = [sys.executable, "-m", "bus", "--host", "127.0.0.1", "--port", str(port),
            "--forward", f"127.0.0.1:{free_port()}", "--sessions", str(tmp_path)]
    producer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    path = tmp_path / "held2.jsonl"

    def readings(seqs, expect_lines):
        for seq in seqs:
            producer.sendto(msg(seq), ("127.0.0.1", port))
        deadline = time.time() + 5
        while (not path.exists() or len(path.read_text().splitlines()) < expect_lines) and time.time() < deadline:
            time.sleep(0.02)

    first = subprocess.Popen(argv, cwd=REPO, stderr=subprocess.PIPE, text=True)
    try:
        assert "listening on" in first.stderr.readline()
        producer.sendto(cmd("record_start", session="held2", purpose="heldout", walker="w1"), ("127.0.0.1", port))
        readings(range(1, 21), 21)
    finally:
        first.kill()                                    # no clean shutdown at all
        first.wait(5)
        first.stderr.close()
    second = subprocess.Popen(argv, cwd=REPO, stderr=subprocess.PIPE, text=True)
    try:
        log = [second.stderr.readline() for _ in range(2)]
        readings(range(21, 41), 41)
        producer.sendto(cmd("record_stop"), ("127.0.0.1", port))
        deadline = time.time() + 5
        while (tmp_path / ".open").exists() and time.time() < deadline:
            time.sleep(0.02)
    finally:
        second.terminate()
        second.wait(5)
        second.stderr.close()
        producer.close()
    assert any("appending to it again" in line for line in log)
    got = lines(path)
    assert [m["type"] for m in got] == ["meta"] + ["rssi"] * 40
    assert [m["seq"] for m in got[1:]] == list(range(1, 41))


def test_link_report_says_which_links_flow_and_which_are_silent(bus):
    assert bus.link_ids[:2] == ["pi5>unoq:wifi", "pi5>unoq:ble"]     # from radio/nodes.json
    for seq in range(1, 61):
        bus.handle(msg(seq, link="west>pi5:ble"), A)
    for seq in range(1, 31):
        bus.handle(msg(seq, link="pi5>unoq:wifi", kind="wifi", tx="pi5", rx="unoq"), B)
    bus.handle(msg(1, "label", zone=2), B)                              # not a link
    line = bus.link_report(30.0)
    assert line == ("links: pi5>unoq:wifi 1.0/s, west>pi5:ble 2.0/s; nothing from: "
                    "pi5>unoq:ble, east>unoq:ble, west>unoq:ble, east>pi5:ble")
    assert bus.link_report(30.0).startswith("links: no rssi; nothing from: pi5>unoq:wifi")   # counts reset


def test_link_report_lists_a_link_it_doesnt_know_last(bus):
    bus.link_ids = ["east>pi5:ble"]
    bus.handle(msg(1, link="east>pi5:ble"), A)
    bus.handle(msg(2, link="odd>link:ble"), A)
    assert bus.link_report(1.0) == "links: east>pi5:ble 1.0/s, odd>link:ble 1.0/s"


def test_a_link_going_quiet_and_coming_back_is_said_once_each(caplog, tmp_path):
    caplog.set_level("INFO", logger="bus")
    t = [1000]
    b = Bus(sessions=tmp_path, clock=lambda: t[0])
    b.handle(msg(1, link="west>pi5:ble"), A)
    b.watch_links(3999)                                  # 2.999 s: still fine
    t[0] = 2000
    b.handle(msg(1, "label", zone=1), B)                 # labels aren't links
    for now in (4000, 4500, 9000):
        b.watch_links(now)
    t[0] = 9000
    b.handle(msg(2, link="west>pi5:ble"), A)
    b.handle(msg(3, link="west>pi5:ble"), A)
    said = [r.getMessage() for r in caplog.records if "west>pi5" in r.getMessage()]
    assert said == ["west>pi5:ble quiet for 3 s", "west>pi5:ble back after 8 s"]


def test_a_link_that_never_sent_is_never_called_quiet(caplog, tmp_path):
    b = Bus(sessions=tmp_path, clock=lambda: 1000)
    b.watch_links(10**9)
    assert not [r for r in caplog.records if "quiet" in r.getMessage()]
