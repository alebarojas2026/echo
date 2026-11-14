"""radio/nodes.json as Python: link ids and beacon payloads (CONTRACTS.md section 3).

    from radio.nodes import LINKS, BEACONS
    LINKS["east>unoq:ble"]          # {"tx": "east", "rx": "unoq", "kind": "ble", ...}
    BEACONS[b"\\xff\\xffRSE"]         # "east"
"""
import json
from pathlib import Path

PATH = Path(__file__).with_name("nodes.json")
DOC = json.loads(PATH.read_text(encoding="utf-8"))

# link id -> the link entry from nodes.json
LINKS = {link["id"]: link for link in DOC["links"]}

# Manufacturer Specific Data payload (company id first, as it sits in the advert) -> beacon node.
# Beacons are matched by this, never by MAC.
BEACONS = {bytes.fromhex(p["data_hex"]): p["node"] for p in DOC["beacons"]["payloads"]}
