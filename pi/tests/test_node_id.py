"""One radio node program for every Pi that both advertises and listens (#460), checked with a
nodes.json that has a second Pi, pi5b with beacon B, the way #415 adds it."""
import json
import socket

import pytest

from pi import radio_node
from radio import hci, hci_scan
from radio.tests.fakes import FakeController, fixture

B = bytes.fromhex("FFFF525342")
PI_B_LINKS = {
    "pi5>pi5b:ble": {"id": "pi5>pi5b:ble", "tx": "pi5", "rx": "pi5b", "kind": "ble"},
    "east>pi5b:ble": {"id": "east>pi5b:ble", "tx": "east", "rx": "pi5b", "kind": "ble"},
    "west>pi5b:ble": {"id": "west>pi5b:ble", "tx": "west", "rx": "pi5b", "kind": "ble"},
    "pi5b>pi5:ble": {"id": "pi5b>pi5:ble", "tx": "pi5b", "rx": "pi5", "kind": "ble"},
}


@pytest.fixture
def two_pis(monkeypatch):
    """radio/nodes.json as it reads with Pi B in it, for the node and the shared scanner."""
    links = {**radio_node.LINKS, **PI_B_LINKS}
    beacons = {**radio_node.BEACONS, B: "pi5b"}
    for module in (radio_node, hci_scan):
        for name, value in (("LINKS", links), ("HEARD", links), ("BEACONS", beacons)):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, value)


def adv_data(fake):
    return next(p for p in fake.sent if p[1:3] == bytes([0x08, 0x20]))[4:]


def test_pi5_by_default_advertises_s_and_reports_the_links_it_hears():
    from radio.nodes import LINKS
    assert radio_node.RX == "pi5"
    assert "pi5" in radio_node.RADIO_NODES   # and pi5b once nodes.json has the desk layout
    heard = tuple(link for link, e in LINKS.items() if e["rx"] == "pi5" and e["kind"] == "ble")
    assert radio_node.heard_by("pi5") == radio_node.PI_LINKS == heard
    assert heard[:2] == ("east>pi5:ble", "west>pi5:ble")   # Pi A's line starts with these (pi.check)
    fake = FakeController()
    radio_node.run(hci.Hci(fake), bus_sock=None, stop=lambda: True, log=lambda line: None)
    assert adv_data(fake)[:8] == bytes.fromhex("07 06 FF FFFF525353")


def test_each_node_advertises_its_own_letter(two_pis):
    assert radio_node.beacon_letter("pi5b") == "B"
    fake = FakeController()
    radio_node.run(hci.Hci(fake), stop=lambda: True, log=lambda line: None, node="pi5b")
    assert adv_data(fake)[:8] == bytes.fromhex("07 06 FF FFFF525342")


def test_pi_b_forwards_its_three_links(two_pis):
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    srv.settimeout(1.0)
    host, port = srv.getsockname()
    fake = FakeController(events=[fixture("legacy_report_east"), fixture("legacy_reports_three")])
    seen = radio_node.run(hci.Hci(fake), bus_host=host, bus_port=port, stop=lambda: fake.drained, seen={},
                          log=lambda line: None, node="pi5b")
    got = [json.loads(srv.recvfrom(4096)[0]) for _ in range(3)]
    srv.close()
    assert [m["link"] for m in got] == ["east>pi5b:ble", "west>pi5b:ble", "pi5>pi5b:ble"]
    assert all(m["rx"] == "pi5b" for m in got)
    assert sorted(seen) == ["east>pi5b:ble", "pi5>pi5b:ble", "west>pi5b:ble"]
    assert radio_node.heard_by("pi5b") == ("pi5>pi5b:ble", "east>pi5b:ble", "west>pi5b:ble")


def test_status_line_and_summary_list_the_nodes_own_links(two_pis):
    bus = radio_node.BusSender(None, ("127.0.0.1", 9), rx="pi5b")
    line = radio_node.status_line({"pi5>pi5b:ble": 40}, 10.0, bus, 0, radio_node.heard_by("pi5b"))
    assert line.startswith("[pi.radio_node] pi5>pi5b:ble 4.0/s, east>pi5b:ble 0.0/s, west>pi5b:ble 0.0/s;")
    rows = radio_node.summary({}, {}, 1.0, radio_node.heard_by("pi5")).splitlines()[1:]
    assert [r.split()[0] for r in rows] == ["east>pi5:ble", "west>pi5:ble", "pi5b>pi5:ble"]



def test_pi_check_still_reads_pi_a_status_line_with_pi_b_in_it(two_pis):
    from pi import check
    bus = radio_node.BusSender(None, ("127.0.0.1", 9))
    line = radio_node.status_line({"east>pi5:ble": 200, "west>pi5:ble": 190, "pi5b>pi5:ble": 300}, 10.0, bus, 0,
                                  radio_node.heard_by("pi5"))
    m = check.STATUS.search(line)
    assert m and (m["east"], m["west"], m["failed"]) == ("20.0", "19.0", "0")
