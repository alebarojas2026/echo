"""radio.link_stats: per-link spread and drift from session lines, and a capture through a real bus."""
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from radio.link_stats import buckets, capture, link_stats, main, readings, table

REPO = Path(__file__).resolve().parents[2]


def rssi(link, t, dbm, **extra):
    return json.dumps({"v": 2, "type": "rssi", "t": t, "seq": 0, "src": "live", "link": link,
                       "kind": "ble", "tx": link.split(">")[0], "rx": "unoq", "dbm": dbm, "recv_t": t, **extra})


def test_readings_keep_only_rssi_by_recv_t():
    lines = [json.dumps({"v": 2, "type": "meta", "session": "f1"}), "not json",
             rssi("east>unoq:ble", 1000, -60), rssi("east>unoq:ble", 1100, -62, recv_t=1150),
             json.dumps({"v": 2, "type": "label", "recv_t": 1200})]
    assert readings(lines) == {"east>unoq:ble": [(1000, -60), (1150, -62)]}


def test_spread_and_rate():
    # 10 readings a second for 2 s, alternating -60 / -62.
    points = [(1000 + 100 * i, -60 if i % 2 else -62) for i in range(21)]
    s = link_stats(points)
    assert s["n"] == 21 and s["rate"] == pytest.approx(10.5)
    assert s["median"] == -62 and s["std"] == pytest.approx(1.0, abs=0.01)
    assert s["std_half_s"] < 0.5          # the 0.5 s means average the alternation out
    assert s["drift"] is None             # under 2 minutes


def test_drift_is_the_spread_of_minute_medians():
    # 3 minutes at 1 reading a second: -60, then -61, then -63.
    points = [(i * 1000, -60 - (0, 1, 3)[i // 60]) for i in range(180)]
    assert link_stats(points)["drift"] == pytest.approx(3.0)
    assert [len(b) for b in buckets(points, 60_000)] == [60, 60, 60]


def test_table_lists_links_in_nodes_json_order_and_the_missing_ones():
    by_link = {"west>unoq:ble": [(0, -50), (1000, -52)], "pi5>unoq:wifi": [(0, -61), (500, -61), (1000, -61)]}
    lines = table(by_link).splitlines()
    assert lines[1].split()[:4] == ["pi5>unoq:wifi", "3", "3.0", "-61.0"]
    assert lines[2].split()[:4] == ["west>unoq:ble", "2", "2.0", "-51.0"]
    assert lines[3].startswith("no readings: pi5>unoq:ble, east>unoq:ble")


def test_main_on_a_file(tmp_path, capsys):
    path = tmp_path / "f1.jsonl"
    path.write_text("\n".join(rssi("east>pi5:ble", 1000 + 100 * i, -70) for i in range(11)))
    main([str(path)])
    assert "east>pi5:ble" in capsys.readouterr().out


def test_main_says_what_is_missing(tmp_path):
    with pytest.raises(SystemExit, match="radio-sight-bus running"):
        main([str(tmp_path / "nothing.jsonl")])
    (tmp_path / "empty.jsonl").write_text(json.dumps({"type": "meta"}))
    with pytest.raises(SystemExit, match="no rssi readings"):
        main([str(tmp_path / "empty.jsonl")])


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_capture_records_through_a_real_bus(tmp_path):
    port = free_port()
    bus = subprocess.Popen([sys.executable, "-m", "bus", "--host", "127.0.0.1", "--port", str(port),
                            "--forward", f"127.0.0.1:{free_port()}", "--sessions", str(tmp_path)],
                           cwd=REPO, stderr=subprocess.PIPE, text=True)
    reader = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        assert "listening on" in bus.stderr.readline()

        def during(seconds):   # stands in for the readers while the capture records
            for i in range(5):
                reader.sendto(rssi("east>unoq:ble", int(time.time() * 1000), -60 - i).encode(), ("127.0.0.1", port))
            time.sleep(0.2)

        capture("flutter-test", 0.3, bus=("127.0.0.1", port), sleep=during)
    finally:
        bus.terminate()
        bus.wait(5)
        bus.stderr.close()
        reader.close()
    lines = (tmp_path / "flutter-test.jsonl").read_text().splitlines()
    assert json.loads(lines[0])["purpose"] == "demo"
    assert len(readings(lines)["east>unoq:ble"]) >= 5
