"""The seam: both board readers through a real `python -m bus`, read where the brain listens.

The readers run on their test stand-ins (a fake station for iw, the fake HCI controller), so this
checks ports, formats, recv_t and the per-socket seq counters end to end, without hardware.
"""
import json
import socket
import subprocess
import sys
from pathlib import Path

from contracts.check import errors
from radio import hci, hci_scan, wifi_rssi
from radio.tests.fakes import FakeController, fixture

REPO = Path(__file__).resolve().parents[2]


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_board_readers_reach_the_brain_through_the_bus(tmp_path):
    brain = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    brain.bind(("127.0.0.1", 0))
    brain.settimeout(1.0)
    port = free_port()
    bus = subprocess.Popen([sys.executable, "-m", "bus", "--host", "127.0.0.1", "--port", str(port),
                            "--forward", f"127.0.0.1:{brain.getsockname()[1]}", "--sessions", str(tmp_path)],
                           cwd=REPO, stderr=subprocess.PIPE, text=True)
    ble_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        assert "listening on" in bus.stderr.readline()

        # Wi-Fi: six polls with rx packets going up give five readings.
        polls = [(-60 - i, 100 + i) for i in range(6)]
        reader = wifi_rssi.Reader("wlan0", "<bssid>", read=lambda *_: polls.pop(0), say=lambda _: None)
        wifi_rssi.run(bus_host="127.0.0.1", bus_port=port, rate_hz=1000, stop=lambda: not polls,
                      reader=reader, pinger=wifi_rssi.Pinger("10.42.0.1", 0))

        # Bluetooth: east, then west and pi5 (the near misses in between are dropped).
        fake = FakeController(events=[fixture("legacy_report_east"), fixture("legacy_report_near_misses"),
                                      fixture("legacy_reports_three")])
        emit = hci_scan.make_bus_emitter(ble_sock, ("127.0.0.1", port), "unoq")
        hci_scan.run(hci_scan.BeaconScanner(hci.Hci(fake), "unoq"), emit, stop=lambda: fake.drained,
                     say=lambda _: None)

        got = []
        while True:
            try:
                got.append(json.loads(brain.recv(65535)))
            except socket.timeout:
                break
    finally:
        bus.terminate()
        bus.wait(5)
        bus.stderr.close()
        ble_sock.close()
        brain.close()

    for m in got:
        assert errors(m) == [], m
        assert isinstance(m["recv_t"], int)
    wifi = [m for m in got if m["kind"] == "wifi"]
    ble = [m for m in got if m["kind"] == "ble"]
    assert [(m["link"], m["dbm"], m["seq"]) for m in wifi] == \
        [("pi5>unoq:wifi", -61 - i, i) for i in range(5)]
    assert [(m["link"], m["seq"]) for m in ble] == \
        [("east>unoq:ble", 0), ("west>unoq:ble", 1), ("pi5>unoq:ble", 2)]
