import json

import pytest

from sim import fake, replay, scrub
from sim.wire import encoder

# Made-up addresses, built from pieces so no address-shaped text sits in the repo.
PARTS = ["02", "00", "5e", "10", "00", "01"]
MACS = [":".join(PARTS), "-".join(PARTS).upper(), ".".join("".join(PARTS)[i:i + 4] for i in (0, 4, 8))]
RSSI = {"v": 2, "type": "rssi", "t": 1763149512120, "seq": 881, "src": "live", "recv_t": 1763149512125,
        "link": "east>pi5:ble", "kind": "ble", "tx": "east", "rx": "pi5", "dbm": -61}


def clean(msg):
    line, found = scrub.scrub_line(json.dumps(msg))
    return json.loads(line), found


def test_contract_messages_are_untouched():
    assert clean(RSSI) == (RSSI, [])
    encode = encoder(1763149500000, src="live")
    for e in fake.simulate(fake.load_path("zone_tour")):
        line = encode(e)
        assert scrub.scrub_line(line) == (line, [])
    narration = {"v": 2, "type": "narration", "t": 1, "seq": 9, "src": "live", "text": "Someone just walked into zone 2.",
                 "event_id": "e123", "event_kind": "enter", "gen_ms": 6120, "source": "llm", "model": "m"}
    assert clean(narration) == (narration, [])


@pytest.mark.parametrize("key", ["mac", "bssid", "BSSID", "addr", "ssid", "name", "local_name", "device_name", "hostname"])
def test_identifier_fields_are_deleted(key):
    out, found = clean({**RSSI, key: "Someone's Phone"})
    assert out == RSSI and found == [key]


@pytest.mark.parametrize("mac", MACS)
def test_mac_addresses_are_blanked_anywhere(mac):
    out, found = clean({**RSSI, "note": f"seen {mac} twice", "extra": {"raw": [mac.upper()]}, mac: 1})
    text = json.dumps(out).lower()
    assert mac.lower() not in text and len(found) == 3
    assert out["note"] == "seen [removed] twice" and out["extra"]["raw"] == ["[removed]"]
    assert {k: v for k, v in out.items() if k in RSSI} == RSSI


def test_nested_identifiers_are_deleted():
    out, found = clean({**RSSI, "adv": {"name": "Kitchen Speaker", "mfg": "FFFF5253", "peer": MACS[0]}})
    assert out["adv"] == {"mfg": "FFFF5253"} and sorted(found) == ["name", "peer"]


def test_numbers_and_ids_that_only_look_a_bit_like_macs_survive():
    msg = {**RSSI, "session": "s12", "event_id": "e123", "mfg": "FFFF 52 53 45", "time": "12:30:45", "hex": "0a1b2c3d4e5f6a"}
    assert clean(msg) == (msg, [])


def test_non_json_lines_are_scrubbed_as_text():
    line, found = scrub.scrub_line(f"# captured from {MACS[0]}")
    assert line == "# captured from [removed]" and found == ["mac"]


def dirty_session(tmp_path):
    encode = encoder(1763149500000, src="live")
    lines = []
    for i, e in enumerate(e for e in fake.simulate(fake.load_path("zone_tour")) if e["t"] < 1):
        msg = json.loads(encode(e))
        if msg["type"] == "rssi" and i % 3 == 0:
            msg.update(bssid=MACS[0], name="Someone's Laptop")
        lines.append(json.dumps(msg))
    f = tmp_path / "s.jsonl"
    f.write_text("\n".join(lines) + "\n")
    return f


def test_cli_writes_a_clean_copy_that_passes_check_and_still_replays(tmp_path, capsys):
    src, dst = dirty_session(tmp_path), tmp_path / "keep.jsonl"
    assert scrub.main(["--check", str(src)]) == 1
    assert scrub.main([str(src), str(dst)]) == 0
    assert "identifiers in" in capsys.readouterr().err
    text = dst.read_text()
    assert MACS[0] not in text and "Laptop" not in text and "bssid" not in text
    assert len(text.splitlines()) == len(src.read_text().splitlines())
    assert scrub.main(["--check", str(dst)]) == 0
    with open(dst) as f:
        assert len(list(replay.read(f))) == len(text.splitlines())


def test_cli_prints_to_stdout_without_a_destination(tmp_path, capsys):
    src = dirty_session(tmp_path)
    assert scrub.main([str(src)]) == 0
    out = capsys.readouterr().out
    assert MACS[0] not in out and all(json.loads(l)["v"] == 2 for l in out.splitlines())
