"""Checks a beacon build: its advertising data is what radio/hci.py keeps for that letter.

    python3 beacon/check_advert.py <build>/beacon.ino.bin E

Looks for the whole LE Set Advertising Data parameter block (length, 10 bytes of data, zero padding to 31)
exactly once in the binary, and runs those 10 bytes through the scanner's own parser.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from radio import hci  # noqa: E402
from radio.nodes import BEACONS, DOC  # noqa: E402


def main(binary_path: str, letter: str) -> None:
    # the square's beacons, and the optional hall beacons when radio/nodes.json has them
    payloads = {p["id"]: p for p in DOC["beacons"]["payloads"] + (DOC.get("hall") or {}).get("beacons", [])}
    if letter not in payloads:
        sys.exit(f"{letter} has no payload in radio/nodes.json, so no scanner would keep it")
    payload = bytes.fromhex(payloads[letter]["data_hex"])
    data = bytes([0x02, 0x01, 0x06]) + bytes([len(payload) + 1, hci.AD_MANUFACTURER]) + payload
    block = bytes([len(data)]) + data.ljust(31, b"\0")

    found = Path(binary_path).read_bytes().count(block)
    if found != 1:
        sys.exit(f"advertising data for {letter} found {found} times in {binary_path}, expected once")
    nodes = [BEACONS.get(p) for p in hci.manufacturer_data(data)]
    if nodes != [payloads[letter]["node"]]:
        sys.exit(f"the scanner reads {data.hex(' ')} as {nodes}")
    print(f"beacon {letter}: advertising data {data.hex(' ')} -> {nodes[0]}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
