"""The optional hall beacons H and J (issue #358): the scanners keep them, the core links don't notice.

The HCI packets are built here, in the same layout as fixtures/hci/legacy_report_east.hex. The traffic
in the load test is synthetic: it shows what the scanner's code does with the extra adverts, not what
the radio hears in a full hall.
"""
import json
import random
import socket
import struct
import time

import pytest

from radio import hci
from radio.hci_scan import BeaconScanner, kept, make_bus_emitter, run, summary
from radio.nodes import BEACONS, DOC, HALL_LINKS, HEARD, LINKS, RECEIVERS
from radio.tests.fakes import FakeController

CORE = [link["id"] for link in DOC["links"]]     # whatever nodes.json lists: the core links


def report(letter: str, rssi: int, company=b"\xff\xff") -> bytes:
    """One legacy LE Advertising Report carrying manufacturer data <company> 52 53 <letter>."""
    data = bytes([0x02, 0x01, 0x06, 0x06, 0xFF]) + company + b"RS" + letter.encode()
    body = bytes([hci.LE_ADV_REPORT, 1, 0x03, 0x01]) + bytes(6) + bytes([len(data)]) + data + struct.pack("b", rssi)
    return bytes([hci.EVENT_PKT, hci.EV_LE_META, len(body)]) + body


def test_core_links_are_the_ones_listed_and_hall_links_are_apart():
    assert list(LINKS) == CORE     # what the brain's health and x-ray are built from
    assert RECEIVERS == [n["id"] for n in DOC["nodes"] if "receiver" in n["roles"]] and "unoq" in RECEIVERS
    # a hall link is any link whose tx is a hall beacon: one per receiver in nodes.json, none of them listed
    assert list(HALL_LINKS) == [f"{tx}>{rx}:ble" for rx in RECEIVERS for tx in ("h", "j")]
    assert not set(HALL_LINKS) & set(CORE) and list(HEARD) == CORE + list(HALL_LINKS)
    assert not any(link["tx"] in ("h", "j") for link in DOC["links"])
    for link_id, link in HALL_LINKS.items():
        assert link == {"id": link_id, "tx": link_id[0], "rx": link_id[2:-4], "kind": "ble"}


def test_hall_section_of_nodes_json():
    hall = DOC["hall"]
    assert [(b["node"], b["id"], b["data_hex"]) for b in hall["beacons"]] == [
        ("h", "H", "FFFF525348"), ("j", "J", "FFFF52534A")]
    core = {p["id"] for p in DOC["beacons"]["payloads"]}
    nodes = {b["node"] for b in hall["beacons"]}
    assert not core & {b["id"] for b in hall["beacons"]} and not nodes & {n["id"] for n in DOC["nodes"]}
    for b in hall["beacons"]:
        assert BEACONS[bytes.fromhex(b["data_hex"])] == b["node"]
        xyz = b["xyz_m"]     # null until measured in the room; then three numbers, as far out as it really is
        assert xyz is None or (len(xyz) == 3 and all(isinstance(v, (int, float)) for v in xyz))
    assert "links" not in hall     # hall links are not listed: they follow from the beacons and the receivers


@pytest.mark.parametrize("letter, rx, link", [
    ("H", "unoq", "h>unoq:ble"), ("J", "unoq", "j>unoq:ble"), ("H", "pi5", "h>pi5:ble"), ("J", "pi5", "j>pi5:ble"),
])
def test_a_hall_advert_is_kept_as_its_link(letter, rx, link):
    assert kept(report(letter, -84), rx) == [(link, -84)]


def test_other_letters_and_other_companies_are_still_dropped():
    assert kept(report("C", -70), "unoq") == []
    assert kept(report("h", -70), "unoq") == []
    assert kept(report("H", -70, company=b"\x4c\x00"), "unoq") == []
    assert kept(report("H", hci.RSSI_UNAVAILABLE), "unoq") == []
    assert kept(report("H", -70), "east") == []     # east is no receiver in nodes.json


def test_a_hall_reading_goes_out_as_an_ordinary_rssi_message():
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    srv.settimeout(1.0)
    out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    events = [report("E", -61), report("H", -84), report("J", -90)]
    scanner = BeaconScanner(hci.Hci(fake := FakeController(events=events)), "unoq")
    seen = run(scanner, make_bus_emitter(out, srv.getsockname(), "unoq"), stop=lambda: fake.drained)
    got = [json.loads(srv.recvfrom(4096)[0]) for _ in events]
    srv.close(), out.close()
    assert [m.pop("t") > 0 for m in got] == [True] * 3
    assert got[1:] == [
        {"v": 2, "type": "rssi", "seq": 1, "src": "live", "link": "h>unoq:ble", "kind": "ble", "tx": "h", "rx": "unoq", "dbm": -84},
        {"v": 2, "type": "rssi", "seq": 2, "src": "live", "link": "j>unoq:ble", "kind": "ble", "tx": "j", "rx": "unoq", "dbm": -90},
    ]
    assert got[0]["link"] == "east>unoq:ble" and got[0]["seq"] == 0
    # The Gate 2 table stays the core links' table.
    assert "h>unoq:ble" in seen and "h>unoq" not in summary(seen, 1.0) and "east>unoq:ble" in summary(seen, 1.0)


def traffic(seconds: float, hall: bool, seed: int = 0):
    """Packets a receiver would get in `seconds` if it heard every advert: S about 44 a second, E and W
    25 each, 40 a second from other people's devices, and (hall) H and J at 25 each. In time order."""
    rng = random.Random(seed)
    senders = [("S", 0.0225, -45), ("E", 0.040, -52), ("W", 0.040, -55), ("?", 0.025, -75)]
    packets = []
    for n, (letter, every, level) in enumerate(senders + [("H", 0.040, -84), ("J", 0.040, -88)]):
        beat = random.Random(f"{seed}-{n}")     # each sender has its own stream: adding H and J moves nothing else
        t = beat.uniform(0, every)
        while t < seconds:
            rssi = level + beat.choice((-2, -1, 0, 0, 1, 2))
            packet = report(letter, rssi, company=b"\x4c\x00" if letter == "?" else b"\xff\xff")
            if hall or letter not in "HJ":
                packets.append((t, packet))
            t += every + beat.uniform(-0.002, 0.008)
    rng.shuffle(packets)
    return [p for _, p in sorted(packets, key=lambda tp: tp[0])]


def scan(packets, rx="unoq"):
    out = []
    for packet in packets:
        out.extend(kept(packet, rx))
    return out


def test_the_core_links_readings_are_the_same_with_the_hall_beacons_on():
    without, with_hall = scan(traffic(30.0, hall=False)), scan(traffic(30.0, hall=True))
    assert [r for r in with_hall if r[0] in LINKS] == without
    assert {link for link, _ in without} == {"pi5>unoq:ble", "east>unoq:ble", "west>unoq:ble"}
    extra = [r for r in with_hall if r[0] not in LINKS]
    assert {link for link, _ in extra} == {"h>unoq:ble", "j>unoq:ble"}
    assert 40 <= len(extra) / 30.0 <= 60     # H and J at about 25 a second each, if every advert were heard


def test_what_the_hall_adverts_cost_the_scanner(capsys):
    """Time through kept() and the bus emitter for a minute of traffic, with and without H and J, as if
    every one of their adverts were heard (in a real hall most are lost on the air, before any of this
    code runs). Printed with -s; the bound only catches the scanner becoming many times slower."""
    out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sink = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sink.bind(("127.0.0.1", 0))
    emit = make_bus_emitter(out, sink.getsockname(), "unoq")

    def cost(packets):
        best = float("inf")
        for _ in range(3):
            start = time.perf_counter()
            for packet in packets:
                for link, dbm in kept(packet, "unoq"):
                    emit(link, dbm)
            best = min(best, time.perf_counter() - start)
        return best

    base, hall = traffic(60.0, hall=False), traffic(60.0, hall=True)
    t_base, t_hall = cost(base), cost(hall)
    out.close(), sink.close()
    with capsys.disabled():
        print(f"\n60 s of adverts: core links only {len(base)} packets in {t_base * 1000:.0f} ms; "
              f"with H and J {len(hall)} packets in {t_hall * 1000:.0f} ms "
              f"({(t_hall - t_base) / 60 * 100:.3f}% of one core for the hall adverts, on this machine)")
    assert t_hall < 3.0     # a minute of the worst case costs well under 5% of one core
