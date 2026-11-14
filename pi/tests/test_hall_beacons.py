"""The Pi forwards the optional hall beacons H and J (issue #358) next to east and west."""
import json
import socket

from pi.radio_node import PI_LINKS, run
from radio import hci
from radio.tests.fakes import FakeController
from radio.tests.test_hall_beacons import report


def test_the_pi_forwards_hall_adverts_and_its_own_two_links_as_before():
    events = [report("E", -61), report("H", -86), report("S", -30), report("W", -70), report("J", -91)]
    fake = FakeController(events=events)
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    srv.settimeout(1.0)
    host, port = srv.getsockname()
    seen = run(hci.Hci(fake), bus_host=host, bus_port=port, stop=lambda: fake.drained, seen={})
    got = [json.loads(srv.recvfrom(4096)[0]) for _ in range(4)]
    srv.close()
    assert [(m["link"], m["tx"], m["rx"], m["kind"], m["dbm"], m["seq"]) for m in got] == [
        ("east>pi5:ble", "east", "pi5", "ble", -61, 0),
        ("h>pi5:ble", "h", "pi5", "ble", -86, 1),
        ("west>pi5:ble", "west", "pi5", "ble", -70, 2),     # the Pi's own beacon S is never a link to itself
        ("j>pi5:ble", "j", "pi5", "ble", -91, 3),
    ]
    assert all(m["v"] == 2 and m["type"] == "rssi" and m["src"] == "live" for m in got)
    assert seen["east>pi5:ble"] == [-61] and seen["west>pi5:ble"] == [-70]
    assert PI_LINKS == ("east>pi5:ble", "west>pi5:ble")     # the status line and the Gate 2 summary stay these two
