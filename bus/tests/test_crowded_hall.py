"""The bus in a crowded hall: readers lose most adverts, in bursts, and the bus must keep up.

Simulated traffic only (a seeded random loss), no measurement: what is checked is that the counts
stay exact, the log stays small and nothing backs up.
"""
import json
import logging
import random
import time

from bus.core import LOSS_LOG_S, Bus

LINKS = ["east>unoq:ble", "west>unoq:ble", "pi5>unoq:ble"]


def rssi(seq, link, t):
    return json.dumps({"v": 2, "type": "rssi", "t": t, "seq": seq, "src": "live", "link": link,
                       "kind": "ble", "tx": link.split(">")[0], "rx": "unoq", "dbm": -60}).encode()


class Clock:
    def __init__(self, ms=1_000_000):
        self.ms = ms

    def __call__(self):
        return self.ms


def hall(seconds, hz, loss, rng, bursts=(), links=LINKS):
    """(t_ms, seq, link) for one scanner socket sending `links` at hz each, with `loss` of the
    messages lost at random and everything lost inside each (start_s, end_s) burst."""
    out, seq = [], 0
    step = 1000 / (hz * len(links))
    for i in range(int(seconds * hz * len(links))):
        t = int(i * step)
        lost = rng.random() < loss or any(a * 1000 <= t < b * 1000 for a, b in bursts)
        if not lost:
            out.append((t, seq, links[i % len(links)]))
        seq += 1
    return out, seq


def run(bus, clock, traffic, start=1_000_000, addr=("192.168.77.1", 40000)):
    """Feed the traffic, and watch the links every 500 ms of the clock as serve() does, whether
    anything arrives or not."""
    next_watch = start
    for t, seq, link in traffic:
        while next_watch <= start + t:
            bus.watch_links(next_watch)
            next_watch += 500
        clock.ms = start + t
        bus.handle(rssi(seq, link, start + t), addr)


def test_sixty_percent_loss_is_counted_exactly_with_few_log_lines(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="bus")
    clock, sent = Clock(), []
    bus = Bus(sessions=tmp_path, send=sent.append, clock=clock)
    traffic, total = hall(60, 25, 0.6, random.Random(7))
    run(bus, clock, traffic)
    producer = next(iter(bus.producers.values()))
    first, last = traffic[0][1], traffic[-1][1]
    assert producer.received == len(traffic) == len(sent)
    assert producer.lost == (last - first + 1) - len(traffic)      # every gap, nothing more
    assert 0.55 < producer.lost / (last - first + 1) < 0.65
    loss_lines = [r for r in caplog.records if " lost " in r.getMessage()]
    assert len(loss_lines) <= 60 / LOSS_LOG_S + 1                   # not one per gap (thousands)
    assert sum(int(r.getMessage().split(" lost ")[1].split()[0]) for r in loss_lines) <= producer.lost
    assert [json.loads(m)["seq"] for m in sent] == [seq for _, seq, _ in traffic]   # in order, none held back
    bus.close()


def test_a_burst_of_total_loss_is_quiet_once_and_back_once(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="bus")
    clock = Clock()
    bus = Bus(sessions=tmp_path, clock=clock)
    # 60 % loss all along, and nothing at all from 10 s to 16 s (someone stood in every line)
    traffic, _ = hall(30, 25, 0.6, random.Random(3), bursts=[(10, 16)])
    run(bus, clock, traffic)
    for link in LINKS:
        said = [r.getMessage() for r in caplog.records if r.getMessage().startswith(link)]
        assert said[0] == f"{link} quiet for 3 s"
        assert said[1].startswith(f"{link} back after 6 s") or said[1].startswith(f"{link} back after 7 s")
        assert len([s for s in said if "quiet" in s]) == 1   # 60 % loss alone never reads as quiet
    bus.close()


def test_the_links_line_names_links_under_0_4_of_the_baseline(tmp_path):
    (tmp_path / "baseline.json").write_text(json.dumps({"t": 1, "session": None, "links": {
        "east>unoq:ble": {"base_dbm": -60, "expected_hz": 25.0},
        "west>unoq:ble": {"base_dbm": -60, "expected_hz": 8.0}}}))
    clock = Clock()
    bus = Bus(sessions=tmp_path, clock=clock)
    traffic, _ = hall(10, 8, 0.0, random.Random(1), links=["east>unoq:ble", "west>unoq:ble"])
    run(bus, clock, traffic)
    line = bus.link_report(10.0)
    # east at 8/s against a baseline of 25/s is under 10/s; west at 8/s against 8/s is fine
    assert line.endswith("; under 0.4 x the baseline: east>unoq:ble")
    assert "west>unoq:ble 8.0/s" in line
    bus.close()


def test_no_baseline_no_stale_list(tmp_path):
    bus = Bus(sessions=tmp_path, clock=Clock())
    bus.handle(rssi(0, "east>unoq:ble", 1), ("127.0.0.1", 1))
    assert "baseline" not in bus.link_report(1.0)
    bus.close()


def test_a_minute_of_a_busy_hall_goes_through_quickly(tmp_path):
    # Twelve links at 30/s for a minute, half of it lost, while recording: the bus must handle it
    # far faster than real time, or the receive buffer fills and the brain gets old readings.
    clock = Clock()
    bus = Bus(sessions=tmp_path, clock=clock)
    bus.handle(json.dumps({"v": 2, "type": "cmd", "cmd": "record_start",
                           "args": {"session": "hall", "purpose": "demo"}}).encode(), ("127.0.0.1", 9))
    links = [f"n{i}>unoq:ble" for i in range(12)]
    traffic, _ = hall(60, 30, 0.5, random.Random(5), links=links)
    started = time.perf_counter()
    run(bus, clock, traffic)
    spent = time.perf_counter() - started
    assert spent < 15.0, f"{len(traffic)} messages took {spent:.1f} s"
    assert bus.recorder.lines == len(traffic) + 1   # the meta line too
    bus.close()
