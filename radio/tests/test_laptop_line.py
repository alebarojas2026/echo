"""radio.laptop_line: a laptop's own Wi-Fi reading, sent as pi5><node>:wifi.

No radio here: the reader runs on its fake source (shaped like the readings measured on the kit) and
on stand-ins for osascript, /proc/net/wireless, iw and ping, through a real `python -m bus` where it matters.
"""
import io
import json
import socket
import statistics
import subprocess
import sys
from pathlib import Path

import pytest

from radio import laptop_line as ll

REPO = Path(__file__).resolve().parents[2]
KEYS = {"v", "type", "t", "seq", "src", "link", "kind", "tx", "rx", "dbm"}


class Clock:
    """A test clock: sleep() moves it, nothing waits."""

    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ---- the message ----

def test_the_message_is_an_ordinary_rssi_reading_and_nothing_more():
    msg = json.loads(ll.make_message(-49, 7, now=lambda: 1763149512.12))
    assert msg == {"v": 2, "type": "rssi", "t": 1763149512120, "seq": 7, "src": "live",
                   "link": "pi5>laptop1:wifi", "kind": "wifi", "tx": "pi5", "rx": "laptop1", "dbm": -49}
    assert set(msg) == KEYS                                 # no network name, no address, no device name


def test_each_laptop_sends_its_own_line_named_by_its_node():
    assert [ll.link_for(n) for n in ("laptop1", "laptop2", "laptop3")] == \
        ["pi5>laptop1:wifi", "pi5>laptop2:wifi", "pi5>laptop3:wifi"]
    msg = json.loads(ll.make_message(-57, 0, ll.link_for("laptop3")))
    assert (msg["link"], msg["tx"], msg["rx"], msg["kind"]) == ("pi5>laptop3:wifi", "pi5", "laptop3", "wifi")
    for bad in ("", "My Mac", "Laptop1", "laptop-1", "pi5>x", "1laptop", "a" * 25):
        with pytest.raises(ValueError, match="not a node id"):
            ll.link_for(bad)


def test_a_wrong_node_name_exits_2_and_says_so(capsys):
    assert ll.main(["--node", "My Mac", "--fake"]) == 2
    assert "not a node id like laptop1" in capsys.readouterr().err


def test_only_a_wifi_link_id_is_accepted():
    assert ll.link_parts("pi5>laptop1:wifi") == ("pi5", "laptop1", "wifi")
    for bad in ("laptop", "pi5>laptop:ble", "pi5>laptop", ">laptop:wifi", "a>b>c:wifi"):
        with pytest.raises(ValueError):
            ll.link_parts(bad)


def test_zero_and_nonsense_are_no_reading():
    got = [ll.as_dbm(v) for v in (-49, "-57", -49.0, 0, 5, None, "", "x", -200)]
    assert got == [-49, -57, -49, None, None, None, None, None, None]


# ---- the fake source ----

def test_the_fake_line_is_shaped_like_the_measured_one():
    samples = ll.fake_samples(60, person=[(20, 30)])
    assert len(samples) == int(60 * ll.FAKE_HZ)
    assert all(isinstance(d, int) for _, d in samples)
    empty = [d for t, d in samples if not 20 <= t < 32]
    person = [d for t, d in samples if 22 <= t < 30]
    assert abs(statistics.median(empty) - ll.FAKE_EMPTY_DBM) <= 1 and statistics.pstdev(empty) < 1.2
    assert 7 <= statistics.median(empty) - statistics.median(person) <= 9      # 7 to 9 dB, as measured
    changes = sum(1 for (_, a), (_, b) in zip(samples, samples[1:]) if a != b)
    assert changes < 60                                                          # a value is kept 1 to 2 s
    assert ll.fake_samples(60, person=[(20, 30)]) == samples                     # the same every run


def test_the_reader_sends_at_the_fakes_rate_every_reading_once():
    clock = Clock()
    samples = ll.fake_samples(30)
    source = ll.FakeSource(samples, clock=clock)
    sent = []
    values = ll.run(source, sent.append, hz=50, seconds=30.5, clock=clock, sleep=clock.sleep)
    assert sent == values == [d for _, d in samples]                 # none twice, none lost, in order
    assert abs(len(sent) / 30 - ll.FAKE_HZ) < 0.05                   # 9.3 a second


def test_a_slow_poll_takes_the_newest_reading_and_never_repeats_one():
    clock = Clock()
    source = ll.FakeSource([(0.0, -49), (0.1, -50), (0.2, -51), (5.0, -57)], clock=clock)
    assert source.read() == -49
    clock.sleep(0.25)
    assert source.read() == -51 and source.read() is None
    clock.sleep(10)
    assert source.read() == -57 and source.read() is None and source.done


def test_a_looping_fake_starts_again_on_time():
    clock = Clock()
    source = ll.FakeSource([(0.0, -49), (0.5, -57)], clock=clock, loop=True, span_s=1.0)
    got = []
    for _ in range(40):
        got.append(source.read())
        clock.sleep(0.1)
    assert [v for v in got if v is not None] == [-49, -57] * 4


def test_recorded_lines_are_read_as_seconds_from_the_first(tmp_path):
    path = tmp_path / "line.txt"
    path.write_text("1794726337.81 -49\n1794726337.92 -49\n\nnot a line\n1794726338.02 -50\n", encoding="utf-8")
    got = ll.file_samples(path)
    assert [d for _, d in got] == [-49, -49, -50]
    assert got[0][0] == 0 and abs(got[2][0] - 0.21) < 1e-6


# ---- the loop: fails soft ----

def test_nothing_is_sent_while_the_laptop_is_not_on_the_hotspot():
    clock = Clock()
    source = ll.FakeSource(ll.fake_samples(6), clock=clock)
    said, sent = [], []
    status = ll.Status("192.168.77.2:5600", clock=clock, say=said.append)
    ll.run(source, sent.append, hz=50, seconds=6.2, joined=lambda: clock() >= 103.0, status=status,
           clock=clock, sleep=clock.sleep)                             # joined after 3 s
    assert all("not on the sensing hotspot" in line for line in said[:2])
    assert 0 < len(sent) <= int(3.3 * ll.FAKE_HZ)                      # only what came after joining
    assert "/s" in said[-1] and "dBm" in said[-1]


def test_no_reading_is_said_and_the_reader_keeps_trying():
    clock = Clock()
    values = [None] * 100

    class Radio:
        def read(self):
            return values.pop(0) if values else -49

    said, sent = [], []
    ll.run(Radio(), sent.append, hz=10, seconds=20, status=ll.Status("b:1", clock=clock, say=said.append),
           clock=clock, sleep=clock.sleep)
    assert "no reading" in said[0] and "still trying" in said[0]
    assert "10.0/s  -49 dBm  pi5>laptop1:wifi -> b:1" in said[-1]       # one line a second: rate and last dBm
    assert 19 <= len(said) <= 20 and 99 <= len(sent) <= 101


def test_a_send_that_fails_is_counted_and_the_next_one_goes_out():
    clock = Clock()
    fail = {"left": 15}
    sent, said = [], []

    def send(dbm):
        if fail["left"]:
            fail["left"] -= 1
            raise OSError(101, "Network is unreachable")
        sent.append(dbm)

    class Radio:
        def read(self):
            return -50

    ll.run(Radio(), send, hz=10, seconds=3, status=ll.Status("b:1", clock=clock, say=said.append),
           clock=clock, sleep=clock.sleep)
    assert "not sent (Network is unreachable)" in said[0]
    assert "not sent" not in said[-1] and 14 <= len(sent) <= 16


def test_the_hotspot_check_is_by_network_and_can_be_switched_off():
    assert ll.on_net("10.42.0.57", ll.HOTSPOT_NET) is True
    assert ll.on_net("192.168.1.20", ll.HOTSPOT_NET) is False
    assert ll.on_net(None, ll.HOTSPOT_NET) is False
    assert ll.on_net("192.168.1.20", None) is True and ll.on_net(None, None) is True
    assert ll.local_address("127.0.0.1", free_port()) == "127.0.0.1"   # asks the route; sends nothing


# ---- picking a source ----

def test_another_system_is_said_plainly_and_exits_2(capsys):
    with pytest.raises(ll.Unsupported, match=r"not supported on Windows \(only macOS and Linux\)"):
        ll.pick_source("win32")
    with pytest.raises(ll.Unsupported, match="not supported on sunos5"):
        ll.pick_source("sunos5")
    if sys.platform == "win32":
        assert ll.main([]) == 2
        assert "not supported on Windows" in capsys.readouterr().err


def test_the_first_source_that_starts_is_used_and_the_reasons_are_kept():
    class No:
        name = "pyobjc"

        def __init__(self):
            raise ll.Unsupported("pyobjc is not in this Python")

    class Yes:
        name = "osascript"

        def __init__(self):
            pass

    assert isinstance(ll.pick_source("darwin", {"darwin": (No, Yes)}), Yes)
    assert isinstance(ll.pick_source("darwin", {"darwin": (No, Yes)}, only="osascript"), Yes)
    with pytest.raises(ll.Unsupported, match="pyobjc is not in this Python"):
        ll.pick_source("darwin", {"darwin": (No,)})
    with pytest.raises(ll.Unsupported, match="--source iw is not for macOS"):
        ll.pick_source("darwin", {"darwin": (No, Yes)}, only="iw")
    assert [cls.name for cls in ll.SOURCES["darwin"]] == ["pyobjc", "osascript"]     # macOS first
    assert [cls.name for cls in ll.SOURCES["linux"]] == ["proc", "iw"]
    assert "win32" not in ll.SOURCES


class FakeProc:
    def __init__(self, lines):
        self.stdout = io.StringIO(lines)
        self.code = None
        self.terminated = False

    def poll(self):
        return self.code

    def terminate(self):
        self.terminated, self.code = True, -15

    def wait(self, timeout=None):
        return self.code


def test_osascript_is_one_process_whose_last_fresh_line_is_the_reading(monkeypatch):
    clock = Clock()
    procs = []

    def popen(cmd, **kw):
        assert cmd[:3] == ["osascript", "-l", "JavaScript"] and "rssiValue" in cmd[4]
        procs.append(FakeProc("-49\n-50\n" if not procs else "0\n-57\n"))
        return procs[-1]

    monkeypatch.setattr(ll.threading.Thread, "start", lambda self: None)   # the thread's work is done by hand below
    source = ll.OsascriptSource(popen=popen, clock=clock, which=lambda _: "/usr/bin/osascript", platform="darwin")
    source._pump(procs[0])
    assert source.read() == -50
    clock.sleep(1.0)
    assert source.read() is None                 # a value older than half a second is no reading
    procs[0].code = 1                            # osascript exits ...
    clock.sleep(2.0)
    assert source.read() is None and len(procs) == 2   # ... and is started again
    assert source.why is None
    source._pump(procs[1])
    assert source.read() == -57
    source.close()
    assert procs[1].terminated


def test_the_reader_asks_for_the_signal_and_nothing_that_names_a_network_or_device():
    text = (ll.JXA % {"interval": 0.1}).lower()
    assert "rssivalue" in text
    for word in ("ssid", "hardwareaddress", "scan", "interfacename", "countrycode"):
        assert word not in text
    code = Path(ll.__file__).read_text(encoding="utf-8")
    for call in (".ssid(", ".bssid(", "hardwareAddress", "scanForNetworks", "cachedScanResults"):
        assert call not in code


def test_osascript_and_corewlan_say_why_they_cannot_run_here():
    with pytest.raises(ll.Unsupported):
        ll.OsascriptSource(platform="linux")
    with pytest.raises(ll.Unsupported, match="not found"):
        ll.OsascriptSource(platform="darwin", which=lambda _: None)
    with pytest.raises(ll.Unsupported):
        ll.CoreWLANSource(platform="linux")
    if sys.platform != "darwin":
        with pytest.raises(ll.Unsupported, match="pyobjc's CoreWLAN is not in this Python"):
            ll.CoreWLANSource(platform="darwin")


def test_osascript_that_keeps_exiting_is_said_on_the_status_line(monkeypatch):
    clock = Clock()
    procs = []

    def popen(cmd, **kw):
        procs.append(FakeProc(""))
        procs[-1].code = 1
        return procs[-1]

    monkeypatch.setattr(ll.threading.Thread, "start", lambda self: None)
    source = ll.OsascriptSource(popen=popen, clock=clock, which=lambda _: "/usr/bin/osascript", platform="darwin")
    said = []
    ll.run(source, lambda dbm: None, hz=10, seconds=8, status=ll.Status("b:1", clock=clock, say=said.append),
           clock=clock, sleep=clock.sleep)
    assert 3 <= len(procs) <= 5                                  # tried again every 2 s, never in a spin
    assert "osascript keeps exiting" in said[-1] and "still trying" in said[-1]


# ---- Linux ----

PROC = """Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE
 face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22
%s"""


def test_proc_net_wireless_gives_the_level_of_the_joined_interface(tmp_path):
    assert ll.proc_level(PROC % "wlp2s0: 0000   61.  -49.  -256        0      0      0      0      0        0\n") == -49
    assert ll.proc_level(PROC % " wlan0: 0000   70   -40   -256  0 0 0 0 0 0\n") == -40
    assert ll.proc_level(PROC % "wlan1: 0000    0.    0.  -256  0 0 0 0 0 0\nwlan0: 0000   43.  -67.  -256  0 0 0 0 0 0\n") == -67
    assert ll.proc_level(PROC % "") is None and ll.proc_level("") is None and ll.proc_level(PROC % "junk\nx: a b c\n") is None
    path = tmp_path / "wireless"
    path.write_text(PROC % "wlan0: 0000   61.  -57.  -256  0 0 0 0 0 0\n", encoding="ascii")
    source = ll.ProcWirelessSource(str(path), platform="linux")
    assert source.read() == -57
    path.unlink()
    assert source.read() is None                                 # the file went away: no reading, no crash
    with pytest.raises(ll.Unsupported, match="no "):
        ll.ProcWirelessSource(str(path), platform="linux")
    with pytest.raises(ll.Unsupported):
        ll.ProcWirelessSource(platform="darwin")


def test_iw_link_gives_the_signal_line_and_keeps_nothing_else():
    asked = []

    class Done:
        stdout = "Connected to <address> (on wlan0)\n\tSSID: <name>\n\tfreq: 5180\n\tsignal: -52 dBm\n\ttx bitrate: 433.3\n"

    def run(cmd, **kw):
        asked.append(cmd)
        return Done()

    source = ll.IwLinkSource(platform="linux", which=lambda _: "/usr/sbin/iw", interfaces=lambda: ["wlan0"], run=run)
    assert source.read() == -52 and asked == [["/usr/sbin/iw", "dev", "wlan0", "link"]]
    Done.stdout = "Not connected.\n"
    assert source.read() is None
    assert vars(source).keys() == {"iw", "interfaces", "run"}     # no text from iw is kept

    def broken(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 0.5)

    assert ll.IwLinkSource(platform="linux", which=lambda _: "iw", interfaces=lambda: ["wlan0"], run=broken).read() is None
    with pytest.raises(ll.Unsupported, match="no Wi-Fi interface"):
        ll.IwLinkSource(platform="linux", which=lambda _: "iw", interfaces=lambda: [])
    assert ll.wifi_interfaces("/no/such/folder") == []


# ---- the pings ----

def test_the_ping_is_the_systems_own_and_never_faster_than_it_allows_without_root():
    assert ll.ping_command("192.168.77.2", 10, "darwin") == ["ping", "-n", "-q", "-i", "0.100", "192.168.77.2"]
    assert ll.ping_command("192.168.77.2", 50, "darwin")[4] == "0.100"
    assert ll.ping_command("192.168.77.2", 10, "linux")[4] == "0.200"
    assert ll.ping_command("192.168.77.2", 2, "linux")[4] == "0.500"
    assert ll.ping_command("192.168.77.2", 0, "darwin") is None and ll.ping_command("192.168.77.2", 10, "win32") is None


def test_the_ping_runs_only_on_the_hotspot_is_started_again_and_never_stops_the_reader():
    clock = Clock()
    procs, said = [], []

    def popen(cmd, **kw):
        procs.append(FakeProc(""))
        return procs[-1]

    pinger = ll.Pinger("192.168.77.2", 10, platform="darwin", popen=popen, clock=clock, say=said.append)
    pinger.check(False)
    assert procs == []                                           # not on the hotspot: no ping
    pinger.check(True)
    pinger.check(True)
    assert len(procs) == 1
    procs[0].code = 2                                            # ping exits (the hotspot went away)
    pinger.check(True)
    assert len(procs) == 1                                       # not at once ...
    clock.sleep(2.1)
    pinger.check(True)
    assert len(procs) == 2                                       # ... but after 2 s
    pinger.check(False)
    assert procs[1].terminated                                   # left the hotspot: stopped
    pinger.stop()

    def no_ping(cmd, **kw):
        raise OSError(2, "No such file or directory")

    pinger = ll.Pinger("192.168.77.2", 10, platform="linux", popen=no_ping, clock=clock, say=said.append)
    pinger.check(True)
    pinger.check(True)
    assert len(said) == 1 and "the readings carry on without them" in said[0]


def test_the_loop_tells_the_pinger_once_a_second_whether_this_is_the_hotspot():
    clock = Clock()
    told = []
    ll.run(ll.FakeSource(ll.fake_samples(5), clock=clock), lambda dbm: None, hz=50, seconds=4.5,
           joined=lambda: clock() >= 102.0, tick=told.append, clock=clock, sleep=clock.sleep)
    assert told == [False, False, True, True, True]


# ---- end to end, and the layout ----

def test_the_fake_reader_reaches_the_brains_port_through_the_bus(tmp_path):
    brain = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    brain.bind(("127.0.0.1", 0))
    brain.settimeout(1.0)
    port = free_port()
    bus = subprocess.Popen([sys.executable, "-m", "bus", "--host", "127.0.0.1", "--port", str(port),
                            "--forward", f"127.0.0.1:{brain.getsockname()[1]}", "--sessions", str(tmp_path)],
                           cwd=REPO, stderr=subprocess.PIPE, text=True)
    try:
        assert "listening on" in bus.stderr.readline()
        done = subprocess.run([sys.executable, "-m", "radio.laptop_line", "--node", "laptop2", "--fake", "--seconds", "2",
                               "--bus", f"127.0.0.1:{port}"], cwd=REPO, capture_output=True, text=True, timeout=30)
        assert done.returncode == 0 and "pi5>laptop2:wifi" in done.stdout and "/s" in done.stdout
        got = []
        while True:
            try:
                got.append(json.loads(brain.recv(65535)))
            except socket.timeout:
                break
    finally:
        bus.terminate()
        bus.wait(5)
    assert 12 <= len(got) <= 22                                          # about 9.3 a second for 2 s
    assert [m["seq"] for m in got] == list(range(len(got)))              # one socket, one counter, none lost
    assert all(m["src"] == "sim" and m["link"] == "pi5>laptop2:wifi" and m["rx"] == "laptop2" for m in got)
    assert all(set(m) == KEYS | {"recv_t"} for m in got)
