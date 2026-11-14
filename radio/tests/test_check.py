"""radio.check with every command's output faked. No address other than the contract's in here."""
import json

import pytest

from radio import check, link_stats

ADDRS_OK = "2: hub    inet 192.168.77.2/24 scope global hub\n3: wlan0    inet 10.42.0.57/24 brd 10.42.0.255\n"


def fake_run(outputs):
    """outputs: {command joined by spaces: (exit code, stdout)}; anything else fails with 1."""
    calls = []

    def run(cmd):
        calls.append(" ".join(cmd))
        return outputs.get(" ".join(cmd), (1, ""))
    run.calls = calls
    return run


GOOD = {
    "ip -4 -o addr show": (0, ADDRS_OK),
    "ping -c 2 -W 1 192.168.77.1": (0, ""),
    "iw dev wlan0 link": (0, "Connected to <pi> (on wlan0)\n\tSSID: <ssid>\n"),
    "ip -4 -o addr show dev wlan0": (0, "3: wlan0    inet 10.42.0.57/24 brd 10.42.0.255\n"),
    "ping -c 2 -W 1 10.42.0.1": (0, ""),
    "iw dev wlan0 get power_save": (0, "Power save: off\n"),
    **{f"systemctl is-active {u}": (0, "active\n") for u in check.UNITS},
}


def test_all_good():
    run = fake_run(GOOD)
    assert check.check_tools(which=lambda tool: "/usr/bin/" + tool)[0]
    assert check.check_ethernet(run) == (True, "Ethernet: 192.168.77.2/24 up, the Pi answers")
    assert check.check_wifi("wlan0", run) == (True, "Wi-Fi: wlan0 joined, 10.42.0.1 answers, power saving off")
    assert check.check_services(run)[0]


def test_missing_tools_say_how_to_install():
    ok, text = check.check_tools(which=lambda tool: None if tool == "iw" else "/usr/bin/" + tool)
    assert not ok and text.startswith("tools: iw missing -> sudo apt-get install")


@pytest.mark.parametrize("broken, says", [
    ({"ip -4 -o addr show": (0, "3: wlan0    inet 10.42.0.57/24\n")}, "board/eth.sh"),
    ({"ping -c 2 -W 1 192.168.77.1": (1, "")}, "the Pi (192.168.77.1) doesn't answer"),
])
def test_ethernet_failures(broken, says):
    ok, text = check.check_ethernet(fake_run({**GOOD, **broken}))
    assert not ok and says in text


@pytest.mark.parametrize("broken, says", [
    ({"iw dev wlan0 link": (0, "Not connected.\n")}, "isn't joined"),
    ({"ip -4 -o addr show dev wlan0": (0, "")}, "no 10.42.0.x address"),
    ({"ping -c 2 -W 1 10.42.0.1": (1, "")}, "10.42.0.1 doesn't answer"),
    ({"iw dev wlan0 get power_save": (0, "Power save: on\n")}, "power saving isn't off"),
])
def test_wifi_failures(broken, says):
    ok, text = check.check_wifi("wlan0", fake_run({**GOOD, **broken}))
    assert not ok and says in text


def test_a_stopped_service_is_named():
    ok, text = check.check_services(fake_run({**GOOD, "systemctl is-active radio-sight-hci-scan": (3, "inactive\n")}))
    assert not ok and text.startswith("services: radio-sight-hci-scan not running")


def rssi(link, t):
    return json.dumps({"v": 2, "type": "rssi", "link": link, "dbm": -60, "recv_t": t})


def fake_capture(sessions, links):
    """Stands in for the bus: writes the session file with 10 readings per link."""
    def capture(session, seconds, sleep=None):
        lines = [json.dumps({"v": 2, "type": "meta", "session": session})]
        lines += [rssi(link, 1000 + 100 * i) for link in links for i in range(10)]
        (sessions / f"{session}.jsonl").write_text("\n".join(lines))
    return capture


def test_links_all_flowing_and_the_capture_is_cleaned_up(tmp_path):
    ok, text = check.check_links(5.0, capture=fake_capture(tmp_path, list(link_stats.LINKS)), sessions=tmp_path)
    assert ok and text.startswith("links: pi5>unoq:wifi 2.0/s, pi5>unoq:ble 2.0/s")
    assert list(tmp_path.iterdir()) == []


def test_silent_links_are_named(tmp_path):
    ok, text = check.check_links(5.0, capture=fake_capture(tmp_path, ["pi5>unoq:wifi", "east>unoq:ble"]),
                                 sessions=tmp_path)
    assert not ok
    assert text == ("links: nothing from pi5>unoq:ble, west>unoq:ble, east>pi5:ble, west>pi5:ble "
                    "(flowing: pi5>unoq:wifi 2.0/s, east>unoq:ble 2.0/s)")


def test_no_bus_no_file(tmp_path):
    ok, text = check.check_links(5.0, capture=lambda *a, **k: None, sessions=tmp_path)
    assert not ok and "radio-sight-bus" in text


def test_an_open_recording_is_left_alone(tmp_path):
    (tmp_path / ".open").write_text(json.dumps({"session": "held1"}))
    ok, text = check.check_links(5.0, capture=lambda *a, **k: pytest.fail("captured"), sessions=tmp_path)
    assert not ok and "recording held1" in text


def test_link_stats_capture_refuses_while_recording(tmp_path, monkeypatch):
    (tmp_path / ".open").write_text(json.dumps({"session": "held1"}))
    monkeypatch.setattr(link_stats, "SESSIONS", tmp_path)
    monkeypatch.setattr(link_stats, "capture", lambda *a, **k: pytest.fail("captured"))
    with pytest.raises(SystemExit, match="recording held1"):
        link_stats.main(["--capture", "5"])


def test_main_checks_the_interface_named_in_env(monkeypatch):
    monkeypatch.delenv("WIFI_IFACE", raising=False)
    monkeypatch.setattr(check, "load_env_file", lambda path: monkeypatch.setenv("WIFI_IFACE", "wlan1"))
    seen = []
    monkeypatch.setattr(check, "check_wifi", lambda iface: seen.append(iface) or (True, "wifi"))
    for name in ("check_tools", "check_ethernet", "check_services"):
        monkeypatch.setattr(check, name, lambda: (True, name))
    monkeypatch.setattr(check, "check_links", lambda seconds: (True, "links"))
    check.main([])
    assert seen == ["wlan1"]
