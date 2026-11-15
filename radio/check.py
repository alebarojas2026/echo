"""Check the board's whole radio path before a gate, a baseline or the demo.

    python3 -m radio.check                # on the board, from the repo, no sudo
    python3 -m radio.check --seconds 10   # a longer link capture

One line per check, `ok` or `FAIL` with what to do, then one last line for the board's whole
radio side: `all ok (N links)` or how many checks failed (exit 1). The links are every link in
radio/nodes.json, Pi B's too: they all reach the bus. Once the brain has a baseline
(data/sessions/baseline.json), each link must reach 0.4 x the rate the baseline counted on it,
the brain's own stale rule; before that, the gates' rates. It prints no
BSSID, MAC or address other than the contract's (CONTRACTS.md section 2), so the output can go on
an issue. The link check has the bus record a few seconds (radio.link_stats), so it's skipped
while another recording is open: a capture would end it.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from . import link_stats
from .wifi_rssi import REPO, find_tool, iw_path, joined_elsewhere, load_env_file, settings
from .nodes import LINKS, PIS
from .report_hci import min_rate

UNITS = ("radio-sight-bus", "radio-sight-wifi-rssi", "radio-sight-hci-scan")



def gate_hz(link_id: str) -> float:
    """The pass rate radio/GATE.md uses for a link: 20/s for Wi-Fi (Gate 1); for Bluetooth, Gate 2's
    rate from what the beacon can give (radio.report_hci.min_rate: 12/s for a Pi's beacon, 7.5/s for
    E and W). Built from radio/nodes.json, so a new layout needs no edit."""
    if LINKS[link_id]["kind"] == "wifi":
        return 20.0
    return min_rate(link_id)


def sh(cmd) -> tuple[int, str]:
    """Run a read-only command: (exit code, stdout). A missing program is exit code 127."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.returncode, r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""


def check_tools(which=find_tool):
    missing = [tool for tool in ("iw", "ping", "nmcli") if which(tool) is None]
    if missing:
        return False, (f"tools: {', '.join(missing)} missing -> sudo apt-get install -y iw iputils-ping "
                       "network-manager, while the board still has internet")
    return True, "tools: iw, ping, nmcli"


def check_radios(root="/sys/class/rfkill"):
    """Neither Bluetooth nor Wi-Fi blocked by rfkill (readable without root)."""
    blocked = []
    for entry in sorted(Path(root).glob("rfkill*")):
        try:
            kind = (entry / "type").read_text().strip()
            soft, hard = ((entry / f).read_text().strip() == "1" for f in ("soft", "hard"))
        except OSError:
            continue
        if kind in ("bluetooth", "wlan") and (soft or hard):
            blocked.append(f"{kind} ({'hard: a switch or the firmware' if hard else 'soft'})")
    if blocked:
        return False, (f"radios: {', '.join(blocked)} blocked -> sudo rfkill unblock all, "
                       "then sudo bluetoothctl power on")
    return True, "radios: Bluetooth and Wi-Fi not blocked"


def check_ethernet(run=sh):
    _, addrs = run(["ip", "-4", "-o", "addr", "show"])
    if "192.168.77.2/24" not in addrs:
        return False, "Ethernet: no 192.168.77.2 on the board -> sudo bash board/eth.sh"
    if run(["ping", "-c", "2", "-W", "1", "192.168.77.1"])[0] != 0:
        return False, "Ethernet: 192.168.77.2 is up but the Pi (192.168.77.1) doesn't answer -> pi/eth.sh, the cable"
    return True, "Ethernet: 192.168.77.2/24 up, the Pi answers"


def check_wifi(iface: str, run=sh, iw=None, bssid: str = ""):
    iw = iw or iw_path()
    _, link = run([iw, "dev", iface, "link"])
    if "Connected to" not in link:
        return False, f"Wi-Fi: {iface} isn't joined to the Pi's hotspot -> sudo bash radio/wifi_join.sh"
    if bssid and joined_elsewhere(link, bssid):
        return False, (f"Wi-Fi: {iface} is joined to another access point, not the BSSID in .env "
                       "-> sudo bash radio/wifi_join.sh, and check SENSING_BSSID")
    _, addr = run(["ip", "-4", "-o", "addr", "show", "dev", iface])
    if " 10.42.0." not in addr:
        return False, f"Wi-Fi: {iface} is joined but has no 10.42.0.x address -> check the Pi's hotspot (pi/ap.sh)"
    if run(["ping", "-c", "2", "-W", "1", "10.42.0.1"])[0] != 0:
        return False, "Wi-Fi: 10.42.0.1 doesn't answer, so the reader can't make the Pi send frames"
    _, save = run([iw, "dev", iface, "get", "power_save"])
    if "off" not in save.lower():
        return False, f"Wi-Fi: power saving isn't off on {iface} -> sudo bash radio/wifi_join.sh"
    return True, f"Wi-Fi: {iface} joined, 10.42.0.1 answers, power saving off"


def check_services(run=sh):
    down = [unit for unit in UNITS if run(["systemctl", "is-active", unit])[1].strip() != "active"]
    if down:
        return False, (f"services: {', '.join(down)} not running -> sudo board/deploy.sh --install, "
                       f"then journalctl -u {down[0]} -n 20")
    return True, "services: " + ", ".join(UNITS) + " active"


STALE_FRAC = 0.4  # CONTRACTS.md section 6: a link is stale when its rate is < 0.4 x expected_hz


def baseline_rates(path) -> dict:
    """{link: expected_hz} from the brain's data/sessions/baseline.json; {} when there's none yet."""
    try:
        links = json.loads(Path(path).read_text(encoding="utf-8"))["links"]
        return {link: float(v["expected_hz"]) for link, v in links.items()
                if isinstance(v, dict) and isinstance(v.get("expected_hz"), (int, float)) and v["expected_hz"] > 0}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def floor_hz(link_id: str, expected: dict) -> float:
    """The lowest healthy rate: 0.4 x what the baseline saw on this link (the brain's stale rule),
    or the gate rate before there is a baseline."""
    return STALE_FRAC * expected[link_id] if link_id in expected else gate_hz(link_id)


def check_links(seconds: float, capture=link_stats.capture, sessions=link_stats.SESSIONS, sleep=time.sleep,
                expected=None):
    expected = baseline_rates(Path(sessions) / "baseline.json") if expected is None else expected
    busy = link_stats.open_recording(sessions)
    if busy:
        return False, f"links: not checked, the bus is recording {busy}; see journalctl -u radio-sight-bus"
    session = time.strftime("check-%H%M%S")
    capture(session, seconds, sleep=sleep)
    path = sessions / f"{session}.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False, "links: the bus recorded nothing -> is radio-sight-bus running?"
    finally:
        if path.exists():
            path.unlink()  # a check isn't a session anyone needs
    by_link = link_stats.readings(lines)
    rates = ", ".join(f"{link} {len(by_link[link]) / seconds:.1f}/s" for link in LINKS if link in by_link)
    silent = [link for link in LINKS if link not in by_link]
    if silent:
        return False, f"links: nothing from {', '.join(silent)}" + (f" (flowing: {rates})" if rates else "")
    slow = [link for link in LINKS if len(by_link[link]) / seconds < floor_hz(link, expected)]
    if slow:
        hint = (" (Wi-Fi: journalctl -u radio-sight-wifi-rssi for the ping)"
                if any(LINKS[link]["kind"] == "wifi" for link in slow) else "")
        stale = [f"{link} under {floor_hz(link, expected):.1f}/s" for link in slow if link in expected]
        gate = [f"{link} under {gate_hz(link):g}/s" for link in slow if link not in expected]
        said = ([f"{', '.join(stale)}, stale (0.4 x the baseline's rate)"] if stale else []) + \
               ([f"{', '.join(gate)}, the gates' rates"] if gate else [])
        return False, f"links: {'; '.join(said)}{hint}; {rates}"
    return True, f"links: {rates}" + (" (judged against the baseline's rates)" if expected else "")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="check the board's radio path")
    ap.add_argument("--seconds", type=float, default=5.0, help="length of the link capture")
    args = ap.parse_args(argv)
    load_env_file(REPO / ".env")  # WIFI_IFACE, as the reader's service sees it
    iface = os.environ.get("WIFI_IFACE") or "wlan0"
    bssid = settings()["bssid"]
    results = [check_tools(), check_radios(), check_ethernet(), check_wifi(iface, bssid=bssid),
               check_services(), check_links(args.seconds)]
    for ok, text in results:
        print(f"{'ok  ' if ok else 'FAIL'}  {text}")
    failed = sum(not ok for ok, _ in results)
    # The one line to read: the board's whole radio side, every link in radio/nodes.json.
    print(f"all ok ({len(LINKS)} links)" if not failed else f"{failed} failed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
