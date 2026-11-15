"""The scanner and the Wi-Fi reader in a crowded hall: most adverts and frames lost, in bursts.

Simulated loss (seeded), not a measurement. What is checked: nothing crashes, every reading that
arrives is sent once, the log says each outage once, and both recover with nobody touching them.
The brain turns the lower rate into "stale" (CONTRACTS.md section 6); here the readers only have to
keep going and never invent readings.
"""
import random

from radio import hci
from radio.hci_scan import run
from radio.wifi_rssi import Reader, poll_loop

LINKS = ["pi5>unoq:ble", "east>unoq:ble", "west>unoq:ble"]


class HallScanner:
    """A scanner on a test clock. Each poll takes 50 ms and gives each link's advert with
    probability 1 - loss; nothing at all inside the bursts. start() can be made to fail."""

    def __init__(self, t, rng, loss=0.6, bursts=(), fail_starts=0, error=None):
        self.t, self.rng, self.loss, self.bursts = t, rng, loss, bursts
        self.starts, self.fail_starts, self.stopped = 0, fail_starts, False
        self.error = error or hci.HciError(hci.LE_SET_SCAN_ENABLE, text="no reply in 2.0 s")
        self.delivered = []

    def start(self):
        self.starts += 1
        if 1 < self.starts <= 1 + self.fail_starts:   # the first start works; restarts may not
            raise self.error

    def stop(self):
        self.stopped = True

    def poll(self):
        self.t[0] += 0.05
        if any(a <= self.t[0] < b for a, b in self.bursts):
            return []
        out = [(link, -60 - i) for i, link in enumerate(LINKS) if self.rng.random() >= self.loss]
        self.delivered += out
        return out


def scan(scanner, t, until, emit=None):
    said, sent = [], []
    run(scanner, emit or (lambda link, dbm: sent.append((link, dbm))), stop=lambda: t[0] >= until,
        clock=lambda: t[0], say=said.append)
    return said, sent


def test_sixty_percent_loss_alone_never_restarts_the_scan():
    t = [0.0]
    scanner = HallScanner(t, random.Random(11))
    said, sent = scan(scanner, t, 120.0)
    assert said == [] and scanner.starts == 1 and scanner.stopped
    assert sent == scanner.delivered                     # every advert that arrived, once, in order
    per_link = len(sent) / len(LINKS) / 120.0
    assert 7.0 < per_link < 9.0                           # 40 % of 20 polls a second


def test_a_burst_of_total_loss_restarts_and_recovers_by_itself():
    t = [0.0]
    scanner = HallScanner(t, random.Random(5), bursts=[(30.0, 37.0)])
    said, sent = scan(scanner, t, 60.0)
    assert said[0] == "no beacon adverts for 2 s, restarting the scan"
    assert said[1].startswith("beacon adverts back after 7 s") and len(said) == 2
    assert scanner.starts == 1 + 3                        # at the start, then every 2 s of the burst
    assert sent == scanner.delivered and sent[-1] in scanner.delivered[-3:]   # flowing again at the end


def test_restarts_that_time_out_dont_end_the_scan():
    t = [0.0]
    scanner = HallScanner(t, random.Random(2), bursts=[(10.0, 20.0)], fail_starts=3)
    said, sent = scan(scanner, t, 40.0)
    assert said[:2] == ["no beacon adverts for 2 s, restarting the scan",
                        "restarting the scan failed (HCI command 0x200C: no reply in 2.0 s); trying again every 2 s"]
    assert said[2].startswith("beacon adverts back after 10 s") and len(said) == 3
    assert scanner.starts >= 5 and sent == scanner.delivered and scanner.stopped


def test_a_bus_that_refuses_sends_for_a_while_is_said_once_and_recovers():
    t = [0.0]
    scanner = HallScanner(t, random.Random(9))
    sent = []

    def emit(link, dbm):
        if 5.0 <= t[0] < 8.0:
            raise OSError(101, "Network is unreachable")
        sent.append((link, dbm))

    said, _ = scan(scanner, t, 15.0, emit=emit)
    assert said == ["can't send to the bus ([Errno 101] Network is unreachable); dropping readings until it works",
                    "sending to the bus again"]
    assert sent and len(sent) < len(scanner.delivered)


class HallStation:
    """`iw station get` on a busy radio: 60 % of the polls read nothing (iw timed out), the rest
    read the last frame, whose counter moves only when the Pi's frames got through."""

    def __init__(self, t, rng, loss=0.6, bursts=()):
        self.t, self.rng, self.loss, self.bursts = t, rng, loss, bursts
        self.rx, self.frames = 1000, 0

    def __call__(self, iface, bssid):
        if any(a <= self.t[0] < b for a, b in self.bursts):
            return None, None                              # nothing heard, or the station is gone
        if self.frames and self.rng.random() < self.loss:   # joined at the start
            return None, None
        self.rx += 2
        self.frames += 1
        return -55 - self.frames % 3, self.rx


def reader_run(station, t, seconds, said):
    reader = Reader("wlan0", "x", read=station, say=said.append, link=lambda iface: "Not connected.",
                    clock=lambda: t[0])
    got = []
    poll_loop(reader, got.append, 25.0, seconds, clock=lambda: t[0], sleep=lambda s: t.__setitem__(0, t[0] + s))
    return got


def test_wifi_reader_with_sixty_percent_of_polls_lost_never_says_no_signal():
    t, said = [0.0], []
    station = HallStation(t, random.Random(4))
    got = reader_run(station, t, 60.0, said)
    assert said == ["reading pi5>unoq:wifi on wlan0"]      # misses under 1 s are not "no signal"
    assert len(got) == station.frames - 1                  # every fresh frame but the very first
    assert 8.0 < len(got) / 60.0 < 12.0


def test_wifi_reader_says_a_real_outage_once_and_comes_back_by_itself():
    t, said = [0.0], []
    station = HallStation(t, random.Random(8), bursts=[(20.0, 26.0)])
    got = reader_run(station, t, 40.0, said)
    assert said == ["reading pi5>unoq:wifi on wlan0",
                    "no signal: wlan0 isn't joined to the Pi's hotspot; still trying",
                    "reading pi5>unoq:wifi on wlan0"]
    assert len(got) == station.frames - 1
