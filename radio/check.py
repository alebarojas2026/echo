"""Check the board's whole radio path before a gate, a baseline or the demo.

    python3 -m radio.check                # on the board, from the repo, no sudo
    python3 -m radio.check --seconds 10   # a longer link capture

One line per check, `ok` or `FAIL` with what to do, and exit 1 if anything failed. It prints no
BSSID, MAC or address other than the contract's (CONTRACTS.md section 2), so the output can go on
an issue. The link check has the bus record a few seconds (radio.link_stats), so it's skipped
while another recording is open: a capture would end it.
"""
import argparse
import os
import subprocess
import sys
import time

from . import link_stats
from .wifi_rssi import REPO, find_tool, iw_path, load_env_file
from .nodes import LINKS

UNITS = ("radio-sight-bus", "radio-sight-wifi-rssi", "radio-sight-hci-scan")


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


def check_ethernet(run=sh):
    _, addrs = run(["ip", "-4", "-o", "addr", "show"])
    if "192.168.77.2/24" not in addrs:
        return False, "Ethernet: no 192.168.77.2 on the board -> sudo bash board/eth.sh"
    if run(["ping", "-c", "2", "-W", "1", "192.168.77.1"])[0] != 0:
        return False, "Ethernet: 192.168.77.2 is up but the Pi (192.168.77.1) doesn't answer -> pi/eth.sh, the cable"
    return True, "Ethernet: 192.168.77.2/24 up, the Pi answers"


def check_wifi(iface: str, run=sh, iw=None):
    iw = iw or iw_path()
    _, link = run([iw, "dev", iface, "link"])
    if "Connected to" not in link:
        return False, f"Wi-Fi: {iface} isn't joined to the Pi's hotspot -> sudo bash radio/wifi_join.sh"
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


def check_links(seconds: float, capture=link_stats.capture, sessions=link_stats.SESSIONS, sleep=time.sleep):
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
    return True, f"links: {rates}"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="check the board's radio path")
    ap.add_argument("--seconds", type=float, default=5.0, help="length of the link capture")
    args = ap.parse_args(argv)
    load_env_file(REPO / ".env")  # WIFI_IFACE, as the reader's service sees it
    iface = os.environ.get("WIFI_IFACE") or "wlan0"
    results = [check_tools(), check_ethernet(), check_wifi(iface), check_services(),
               check_links(args.seconds)]
    for ok, text in results:
        print(f"{'ok  ' if ok else 'FAIL'}  {text}")
    if not all(ok for ok, _ in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
