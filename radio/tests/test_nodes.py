"""radio/nodes.py: what it builds from radio/nodes.json, for whatever layout the file holds.

The layout itself (positions, links, zones, spots, letters) is checked against CONTRACTS.md
section 3 and the schemas by contracts/ (contracts/tests/test_layout.py with the desk layout, #415).
Nothing here names a position or a count, so a new layout needs no edit.
"""
import json

import pytest

from radio import nodes


@pytest.fixture(scope="module")
def doc():
    return json.loads(nodes.PATH.read_text(encoding="utf-8"))


def test_links_are_the_files_links_by_id_in_its_order(doc):
    assert list(nodes.LINKS) == [link["id"] for link in doc["links"]]
    for link_id, link in nodes.LINKS.items():
        assert link_id == f'{link["tx"]}>{link["rx"]}:{link["kind"]}'


def test_every_link_joins_two_nodes_and_ends_at_a_receiver(doc):
    by_id = {n["id"]: n for n in doc["nodes"]}
    for link in nodes.LINKS.values():
        assert link["tx"] in by_id and link["rx"] in by_id and link["tx"] != link["rx"]
        assert link["rx"] in nodes.RECEIVERS
        assert link["kind"] in ("wifi", "ble")
        assert ("router" if link["kind"] == "wifi" else "beacon") in by_id[link["tx"]]["roles"]


def test_expected_hz_is_null_or_measured(doc):
    # null until the baseline capture writes it, then a positive rate
    for link in doc["links"]:
        hz = link.get("expected_hz")
        assert hz is None or (isinstance(hz, (int, float)) and hz > 0)


def test_beacons_map_their_advert_bytes_to_their_node(doc):
    payloads = doc["beacons"]["payloads"]
    for p in payloads:
        data = bytes.fromhex(p["data_hex"])
        assert data[:4] == b"\xff\xffRS" and data[4:].decode() == p["id"]   # FFFF 52 53 <letter>
        assert nodes.BEACONS[data] == p["node"]
    # every node with the beacon role advertises, each with its own letter
    beacon_nodes = {n["id"] for n in doc["nodes"] if "beacon" in n["roles"]}
    assert {p["node"] for p in payloads} == beacon_nodes
    assert len({p["id"] for p in payloads}) == len(payloads)


def test_receivers_and_pis_come_from_the_roles(doc):
    assert nodes.RECEIVERS == [n["id"] for n in doc["nodes"] if "receiver" in n["roles"]]
    assert set(nodes.PIS) == {n["id"] for n in doc["nodes"] if {"receiver", "beacon"} <= set(n["roles"])}
    assert set(nodes.PIS) <= set(nodes.RECEIVERS)

