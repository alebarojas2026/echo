"""radio.report_wifi with one Gate 1 table per Wi-Fi link (#459 item 6), and the gate's prompts."""
from radio import wifi_rssi
from radio.report_wifi import GATE_PATH, WIFI_LINKS, report, tables

ROWS = ("**Measured sample rate:** {rate} samples/s\n\n| Run | Baseline dBm | Blocked dBm | Drop dB | Result |\n"
        "|---|---|---|---|---|\n| 1 | -62 | -68 | 6.0 | PASS |\n| 2 | -62 | -68 | 6.0 | PASS |\n"
        "| 3 | -61 | -67 | 6.0 | PASS |\n")
TWO = ["pi5>unoq:wifi", "pi5>pi5b:wifi"]


def gate1(*sections):
    return "## Gate 1 — Wi-Fi link test (#19)\n\n" + "".join(sections) + "\n## Gate 2\n| 1 | -1 | -9 | 8 | PASS |\n"


def section(link, rate="24.6"):
    return f"### {link} (somewhere)\n\n" + ROWS.format(rate=rate)


def test_each_wifi_link_is_judged_on_its_own_table():
    text = gate1(section(TWO[0]), section(TWO[1], rate="12.0"))
    passed, lines = report(text, TWO)
    assert not passed and lines == ["GATE 1 FAIL", "  - pi5>pi5b:wifi: rate 12.0 < 20 samples/s"]
    passed, lines = report(gate1(section(TWO[0]), section(TWO[1])), TWO)
    assert passed and lines[0].startswith("GATE 1 PASS  (pi5>unoq:wifi 24.6 samples/s, pi5>pi5b:wifi 24.6")


def test_a_table_for_a_link_nodes_json_lacks_is_ignored():
    # GATE.md carries Pi B's table before nodes.json has Pi B.
    text = gate1(section(TWO[0]), section(TWO[1], rate="__"))
    assert report(text, TWO[:1])[0]
    assert set(tables(text, TWO[:1])) == {TWO[0]}


def test_a_missing_table_fails():
    passed, lines = report(gate1(section(TWO[0])), TWO)
    assert not passed and "pi5>pi5b:wifi: no Gate 1 table" in lines[1]


def test_no_link_headings_is_the_old_single_table():
    assert report(gate1(ROWS.format(rate="24.6")), TWO[:1])[0]


def test_the_real_gate_md_has_a_table_for_every_wifi_link_and_none_measured():
    text = GATE_PATH.read_text(encoding="utf-8")
    assert set(tables(text, TWO)) == set(TWO)
    passed, lines = report(text)
    assert not passed and all(f"{link}: measured sample rate not recorded" in "".join(lines) for link in WIFI_LINKS)


def test_the_gate_names_the_two_ends_of_its_link(monkeypatch):
    assert wifi_rssi.line_ends() == "the board and the Pi"
    monkeypatch.setattr(wifi_rssi, "TX", "pi5")
    monkeypatch.setattr(wifi_rssi, "RX", "pi5b")
    monkeypatch.setattr(wifi_rssi, "DOC", {"nodes": [{"id": "pi5", "name": "Pi A"}, {"id": "pi5b", "name": "Pi B"}]})
    assert wifi_rssi.line_ends() == "Pi B and Pi A"
