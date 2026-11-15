"""Checks the Pi's side of the radio path, one line per check, before a gate, a baseline or the demo.

    python3 -m pi.check                 # no sudo; exit 1 if anything failed
    python3 -m pi.check --node pi5b     # on Pi B (default: RADIO_NODE from .env, else pi5)

Bluetooth powered, the radio node running and hearing every beacon the layout gives it and sending to the
board, the Ethernet link to the board, and the sensing hotspot. Pi B has no cable and no hotspot of its
own: it checks its two services and that it's joined to Pi A's hotspot. Each FAIL line says what to run.
It prints no device address: only the contract's addresses (CONTRACTS.md section 2).
"""
import os
import re
import subprocess
import sys

ETH = os.environ.get("ETH_IFACE", "eth0")
WIFI = os.environ.get("SENSING_IFACE", "wlan0")
UNIT = "radio-sight-radio-node"

# Pi A's status line: every Bluetooth link it hears with its rate (radio/nodes.json's, whatever the layout holds),
# then the sends.
STATUS = re.compile(r"\[pi\.radio_node\] (?P<rates>\S+>\S+:ble [\d.]+/s[^;]*)"
                    r"; sent (?P<sent>\d+), not sent (?P<failed>\d+)(?: \((?P<why>[^)]*)\))?")


def beacon_of(link: str):
    """(letter, advert data) of the beacon a link listens to, when it is a beacon with no scanner of its
    own (an ESP32); None for a Pi's beacon, whose silence is that Pi's node, and for an unknown link."""
    try:
        from radio.nodes import DOC
    except Exception:   # no layout to read: every link is treated as a Pi's
        return None
    tx = link.split(">")[0]
    roles = next((n.get("roles", []) for n in DOC["nodes"] if n["id"] == tx), None)
    if roles is None or "receiver" in roles:
        return None
    payload = next((p for p in DOC["beacons"]["payloads"] if p["node"] == tx), None)
    return (payload["id"], payload["data_hex"][4:]) if payload else None


def run(*cmd: str) -> tuple[int, str]:
    """Exit code and stdout+stderr of a command; 127 if it isn't installed."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except FileNotFoundError:
        return 127, f"{cmd[0]}: not installed"
    except subprocess.TimeoutExpired:
        return 124, f"{cmd[0]}: no answer in 10 s"
    return r.returncode, r.stdout + r.stderr


def bluetooth(run=run):
    code, out = run("btmgmt", "info")
    settings = re.search(r"current settings:(.*)", out)
    if code == 0 and "hci0" in out and settings and "powered" in settings.group(1).split():
        return True, "Bluetooth: hci0 powered", None
    return False, "Bluetooth: hci0 missing or not powered", \
        "sudo rfkill unblock bluetooth && sudo bluetoothctl power on"


def radio_node(run=run):
    code, out = run("systemctl", "is-active", UNIT)
    if out.strip() != "active":
        state = "not found (no systemctl)" if code == 127 else (out.strip() or "not active")
        return False, f"radio node: {UNIT} is {state}", \
            f"sudo bash pi/install.sh, then: journalctl -u {UNIT} -n 20 --no-pager"
    return True, "radio node: running", None


def radio_status(run=run):
    code, out = run("journalctl", "-u", UNIT, "--since", "-30s", "-o", "cat", "--no-pager")
    lines = [m for m in map(STATUS.search, out.splitlines()) if m]
    if not lines:
        return False, "radio node: no status line in the last 30 s", \
            f"sudo journalctl -u {UNIT} -n 20 --no-pager (no lines at all: run this check with sudo)"
    m = lines[-1]
    failed = int(m["failed"])
    heard = [(link, float(rate)) for link, rate in LINK_RATE.findall(m["rates"])]
    rates = ", ".join(f"{link} {rate:.1f}/s" for link, rate in heard) + f", not sent {failed}"
    if failed:
        return False, f"radio node: {rates} ({m['why'] or 'send failed'})",             "the Ethernet link is down: see the Ethernet line below"
    # A beacon with no scanner of its own (an ESP32) is named by its letter; a Pi's beacon points at that Pi's check.
    silent = [beacon_of(link) for link, rate in heard if rate <= 0 and beacon_of(link)]
    if silent:
        return False, f"radio node: {rates}",             f"nothing heard from beacon {' and '.join(letter for letter, _ in silent)}: check it's powered and advertising "             f"(a phone scanner must show company 0xFFFF, data {', '.join(f'{data} for {letter}' for letter, data in silent)})"
    quiet = [link for link, rate in heard if rate <= 0]
    if quiet:
        return False, f"radio node: {rates}",             f"nothing heard on {', '.join(quiet)}: is Pi B's node running? On Pi B: python3 -m pi.check --node pi5b"
    return True, f"radio node: {rates}", None


def ethernet(run=run):
    code, out = run("ip", "-4", "-o", "addr", "show", "dev", ETH)
    if "192.168.77.1/24" not in out:
        return False, f"Ethernet: {ETH} doesn't have 192.168.77.1/24", \
            f"sudo bash pi/eth.sh, and check the cable to the board (ip -4 addr show dev {ETH})"
    code, _ = run("ping", "-c", "1", "-W", "1", "192.168.77.2")
    if code != 0:
        return False, "Ethernet: 192.168.77.1/24 is up, but the board (192.168.77.2) doesn't answer", \
            "on the board: sudo bash board/eth.sh; check the cable"
    return True, "Ethernet: 192.168.77.1/24, the board answers", None


def hotspot(run=run):
    code, out = run("nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show", "--active")
    if not any(line.startswith("deadzone-ap:") for line in out.splitlines()):
        return False, "hotspot: the deadzone-ap profile isn't active", "sudo bash pi/ap.sh"
    code, out = run("ip", "-4", "-o", "addr", "show", "dev", WIFI)
    if "10.42.0.1/24" not in out:
        return False, f"hotspot: deadzone-ap is active, but {WIFI} doesn't have 10.42.0.1/24", "sudo bash pi/ap.sh"
    return True, "hotspot: up on 10.42.0.1/24", None


def forwarding(run=run):
    """The demo laptop and Pi B, both on the hotspot, reach the board through Pi A (the hotspot's shared mode forwards)."""
    code, out = run("cat", "/proc/sys/net/ipv4/ip_forward")
    if out.strip() != "1":
        return False, "forwarding: off, so the laptop and Pi B's readings can't reach the board", \
            "sudo nmcli connection up deadzone-ap (its shared mode turns forwarding on)"
    return True, "forwarding: on (the laptop and Pi B on the hotspot reach 192.168.77.2)", None


LINK_RATE = re.compile(r"(\S+>\S+:ble) ([\d.]+)/s")
SENT = re.compile(r"; sent (\d+), not sent (\d+)(?: \(([^)]*)\))?")


def radio_status_b(run=run):
    """Pi B: every link on its last status line above 0/s, and its readings reach the board through Pi A."""
    code, out = run("journalctl", "-u", UNIT, "--since", "-30s", "-o", "cat", "--no-pager")
    lines = [line for line in out.splitlines() if line.startswith("[pi.radio_node] ") and SENT.search(line)]
    if not lines:
        return False, "radio node: no status line in the last 30 s", \
            f"sudo journalctl -u {UNIT} -n 20 --no-pager (no lines at all: run this check with sudo)"
    rates = [(link, float(rate)) for link, rate in LINK_RATE.findall(lines[-1])]
    sent = SENT.search(lines[-1])
    text = ", ".join(f"{link} {rate:.1f}/s" for link, rate in rates) + f", not sent {sent[2]}"
    if int(sent[2]):
        return False, f"radio node: {text} ({sent[3] or 'send failed'})", \
            "readings go to the board through Pi A's hotspot: see the hotspot line below"
    silent = [link for link, rate in rates if rate <= 0]
    if silent:
        return False, f"radio node: {text}", f"nothing heard on {', '.join(silent)}: check that beacon is powered"
    return True, f"radio node: {text}", None


def wifi_reader(run=run):
    code, out = run("systemctl", "is-active", "radio-sight-wifi-rssi")
    if out.strip() != "active":
        return False, f"Wi-Fi reader: radio-sight-wifi-rssi is {out.strip() or 'not active'}", \
            "journalctl -u radio-sight-wifi-rssi -n 20 --no-pager"
    return True, "Wi-Fi reader: running", None


def joined(run=run):
    """Pi B: on Pi A's hotspot (a 10.42.0.x address, not .1), and the board answers through Pi A."""
    code, out = run("ip", "-4", "-o", "addr", "show", "dev", WIFI)
    if "inet 10.42.0." not in out or "inet 10.42.0.1/" in out:
        return False, f"hotspot: {WIFI} isn't joined to Pi A's hotspot", \
            "sudo bash radio/wifi_join.sh (SSID, passphrase and BSSID in .env)"
    code, route = run("ip", "-4", "route", "get", "192.168.77.2")
    if code != 0 or "via 10.42.0.1" not in route:
        return False, "hotspot: joined, but there's no route to the board (192.168.77.2) through Pi A", \
            "sudo bash radio/wifi_join.sh with RADIO_NODE=pi5b in .env (it adds 192.168.77.0/24 via 10.42.0.1)"
    code, _ = run("ping", "-c", "1", "-W", "1", "192.168.77.2")
    if code != 0:
        return False, "hotspot: joined, but the board (192.168.77.2) doesn't answer through Pi A", \
            "on Pi A: python3 -m pi.check (Ethernet and forwarding lines)"
    return True, "hotspot: joined to Pi A's, the board answers", None


CHECKS = (bluetooth, radio_node, radio_status, ethernet, hotspot, forwarding)
CHECKS_B = (bluetooth, radio_node, radio_status_b, wifi_reader, joined)


def main(run=run, node=None) -> int:
    node = node or os.environ.get("RADIO_NODE", "pi5")
    failed = 0
    for check in (CHECKS_B if node == "pi5b" else CHECKS):
        ok, line, fix = check(run)
        print(f"{'ok  ' if ok else 'FAIL'}  {line}")
        if not ok:
            failed += 1
            print(f"      fix: {fix}")
    print("all ok" if not failed else f"{failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    sys.exit(main(node=args[args.index("--node") + 1] if "--node" in args else None))
