"""Switch the layout the whole system runs on: python -m radio.use_layout <name>

    python -m radio.use_layout            # says which layout is active and lists the others
    python -m radio.use_layout gate       # one spot between Pi B and the desk: three devices, six links, one zone
    python -m radio.use_layout desk       # the desk strip: five devices, twelve links, two zones

Every part reads radio/nodes.json (CONTRACTS.md section 3), so switching is one copy:
radio/layouts/<name>.json over radio/nodes.json, written whole or not at all. Then restart
what has already read it (on the board: board/deploy.sh, or restart the radio-sight units) and
take a new baseline: recordings, baselines and models from another layout don't fit.

A file that isn't a layout (no nodes, a link between nodes it doesn't have, a zone without a
place) is refused and nothing is changed.
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAYOUTS = HERE / "layouts"
ACTIVE = HERE / "nodes.json"


def names(layouts=LAYOUTS):
    return sorted(p.stem for p in Path(layouts).glob("*.json"))


def problems(doc):
    """Why a parsed file can't be the layout, as plain sentences. Empty when it can."""
    out = []
    if not isinstance(doc, dict) or doc.get("v") != 2:
        return ['it is not {"v": 2, ...}']
    nodes = {n.get("id"): n for n in doc.get("nodes") or [] if isinstance(n, dict)}
    if len(nodes) < 2:
        out.append("it needs two nodes or more")
    for n in nodes.values():
        xyz = n.get("xyz_m")
        if not (isinstance(xyz, list) and len(xyz) == 3 and all(isinstance(v, (int, float)) for v in xyz)):
            out.append(f"node {n.get('id')}: xyz_m is three numbers")
        if not isinstance(n.get("roles"), list):
            out.append(f"node {n.get('id')}: roles is a list")
    links = doc.get("links") or []
    if not links:
        out.append("it has no links")
    for link in links:
        tx, rx, kind = link.get("tx"), link.get("rx"), link.get("kind")
        if link.get("id") != f"{tx}>{rx}:{kind}" or kind not in ("wifi", "ble"):
            out.append(f"link {link.get('id')}: the id is <tx>><rx>:<wifi|ble>")
        elif tx not in nodes or rx not in nodes:
            out.append(f"link {link['id']}: {tx if tx not in nodes else rx} is not one of its nodes")
        elif "receiver" not in (nodes[rx].get("roles") or []):
            out.append(f"link {link['id']}: {rx} is not a receiver")
    zones = doc.get("zones") or []
    ids = [z.get("id") for z in zones]
    if ids != list(range(1, len(ids) + 1)) or not ids:
        out.append("zones are numbered 1, 2, ... with no gaps")
    frame = doc.get("frame") or {}
    if not frame.get("size_m"):
        out.append("frame.size_m is missing")
    for z in zones:
        if not (isinstance(z.get("name"), str) and z["name"].strip()):
            out.append(f"zone {z.get('id')}: it needs a name")
    if len(zones) == 1 and not frame.get("strip_m"):
        out.append("one zone needs frame.strip_m: the spot it covers")
    if len(zones) == 2 and frame.get("zone_split_x_m") is None:
        out.append("two zones need frame.zone_split_x_m")
    for link in links:
        if not isinstance(link.get("crosses_spot", False), bool):
            out.append(f"link {link.get('id')}: crosses_spot is true or false")
    beacons = {p.get("node") for p in (doc.get("beacons") or {}).get("payloads") or []}
    missing = sorted(n for n, node in nodes.items() if "beacon" in (node.get("roles") or []) and n not in beacons)
    if missing:
        out.append(f"no beacon payload for {', '.join(missing)}")
    return out


def active(layouts=LAYOUTS, target=ACTIVE):
    """The name of the layout file radio/nodes.json is a copy of, or None when it is none of them."""
    try:
        now = json.loads(Path(target).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for name in names(layouts):
        if json.loads((Path(layouts) / f"{name}.json").read_text(encoding="utf-8")) == now:
            return name
    return None


def use(name, layouts=LAYOUTS, target=ACTIVE):
    """Copies layouts/<name>.json over nodes.json. Raises ValueError, changing nothing, when it can't."""
    if name not in names(layouts):
        raise ValueError(f"no layout called {name!r}: there is {', '.join(names(layouts)) or 'none'}")
    text = (Path(layouts) / f"{name}.json").read_text(encoding="utf-8")
    try:
        found = problems(json.loads(text))
    except ValueError as e:
        found = [f"it is not JSON ({e})"]
    if found:
        raise ValueError(f"radio/layouts/{name}.json is not a layout: " + "; ".join(found))
    tmp = Path(target).with_name(Path(target).name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, target)
    return json.loads(text)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        now = active()
        print(f"active: {now or 'radio/nodes.json is not a copy of any layout file'}")
        print(f"layouts: {', '.join(names())}")
        return 0
    try:
        doc = use(argv[0])
    except ValueError as e:
        print(f"use_layout: {e}", file=sys.stderr)
        return 1
    print(f"radio/nodes.json is now the {argv[0]} layout: {len(doc['nodes'])} devices, {len(doc['links'])} links, "
          f"{len(doc['zones'])} zone{'s' if len(doc['zones']) != 1 else ''}.")
    print("Restart what has read the old one (on the board: board/deploy.sh), then take a new baseline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
