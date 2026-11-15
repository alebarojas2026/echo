"""board/privacy.py with a fake counter, fake containers and temp folders; GET /privacy on serve.py."""
import json
import subprocess
import threading
import urllib.request

import pytest

from board import privacy, serve

# The meter knows a file by its name or its first bytes, so the tests plant 64-byte stubs that only
# start like these files: a few literal bytes, never a picture, and nothing here encodes one.
STUB = {"jpeg": b"\xff\xd8\xff\xe0" + b"\x00" * 60, "png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 60,
        "mp4": b"\x00\x00\x00\x18ftypisom" + b"\x00" * 60}


def plant(path, kind):
    """Put a stub that starts like a `kind` file at path, in the test's temp folder."""
    path.write_bytes(STUB[kind])


class FakeCounter:
    def __init__(self, value=0):
        self.value, self.why = value, None

    def read(self):
        if self.why:
            raise privacy.Unreadable(self.why)
        return self.value


class FakeContainers:
    def __init__(self, n=0):
        self.n, self.containers, self.why = n, 1, None

    def count(self):
        if self.why:
            raise privacy.Unreadable(self.why)
        return self.n


class Clock:
    def __init__(self, t=1_763_149_500.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def folders(tmp_path):
    data, apps = tmp_path / "data", tmp_path / "ArduinoApps"
    (data / "sessions").mkdir(parents=True)
    (apps / "teacher" / "python").mkdir(parents=True)
    (data / "sessions" / "s01.jsonl").write_text('{"v":2}\n')
    (apps / "teacher" / "python" / "calib.json").write_text("{}")
    (apps / "teacher" / "python" / "label_mode").write_text("off")
    return data, apps


@pytest.fixture
def meter(tmp_path, folders):
    def make(counter=None, containers=None, clock=None, boot="boot-1"):
        log = []
        m = privacy.Meter(counter or FakeCounter(), privacy.FolderScan(folders),
                          containers or FakeContainers(), run_dir=tmp_path / "run",
                          state_dir=tmp_path / "state", clock=clock or Clock(),
                          boot=lambda: boot, log=log.append)
        m.logged = log
        return m
    return make


# ---- images ----

def test_no_images_in_clean_folders(folders):
    assert privacy.FolderScan(folders).count() == 0


@pytest.mark.parametrize("name, data", [
    ("frame.jpg", b"not really"), ("CLIP.MP4", b""), ("x.webp", b""),
    ("frame.bin", STUB["jpeg"]), ("dump", STUB["png"]), ("video.dat", STUB["mp4"]),
])
def test_an_image_or_video_by_name_or_by_its_first_bytes_is_counted(folders, name, data):
    data_dir, apps = folders
    (apps / "teacher" / "python" / name).write_bytes(data)
    assert privacy.FolderScan(folders).count() == 1


def test_images_anywhere_below_are_counted_and_gone_ones_are_not(folders):
    data_dir, apps = folders
    deep = data_dir / "sessions" / "a" / "b"
    deep.mkdir(parents=True)
    plant(deep / "one.png", "png")
    plant(apps / "two.jpeg", "jpeg")
    scan = privacy.FolderScan(folders)
    assert scan.count() == 2
    (deep / "one.png").unlink()
    assert scan.count() == 1


def test_library_icons_are_not_stored_pictures(folders):
    data_dir, apps = folders
    lib = apps / "teacher" / ".cache" / "venv" / "lib" / "site-packages" / "pkg"
    lib.mkdir(parents=True)
    plant(lib / "icon.png", "png")
    assert privacy.FolderScan(folders).count() == 0


def test_a_missing_folder_is_listed_not_counted_as_checked(tmp_path, folders):
    scan = privacy.FolderScan([*folders, tmp_path / "nope"])
    assert scan.count() == 0 and scan.missing == [str(tmp_path / "nope")]


def test_a_folder_that_cant_be_read_is_unreadable_not_zero(folders, monkeypatch):
    def walk(top, onerror):
        onerror(PermissionError(13, "Permission denied", str(top)))
        return iter(())
    monkeypatch.setattr(privacy.os, "walk", walk)
    with pytest.raises(privacy.Unreadable, match="Permission denied"):
        privacy.FolderScan(folders).count()


def test_default_folders_are_where_the_camera_pipeline_or_our_code_could_write(tmp_path):
    env = {"TEACHER_APP": "user:radio-sight-teacher", "TEACHER_HEARTBEAT": "/srv/teacher/heartbeat.json",
           "TEACHER_MODE_FILE": "/srv/teacher/mode", "PRIVACY_DIRS": "/opt/extra:"}
    got = [p.as_posix() for p in privacy.default_folders(env, home=tmp_path)]
    assert got[0].endswith("/data") and got[1] == (tmp_path / "ArduinoApps" / "radio-sight-teacher").as_posix()
    assert (tmp_path / "ArduinoApps").as_posix() not in got   # not every App Lab app: only the teacher's
    assert sum(p.endswith("/srv/teacher") for p in got) == 1 and got[-1].endswith("/opt/extra")


@pytest.mark.parametrize("app, folder", [
    ("user:radio-sight-teacher", "ArduinoApps/radio-sight-teacher"),
    ("radio-sight-teacher", "ArduinoApps/radio-sight-teacher"),
    (None, "ArduinoApps/(TEACHER_APP is not set in .env)"),
])
def test_the_teachers_folder_from_teacher_app(tmp_path, app, folder):
    assert privacy.teacher_folder(app, tmp_path) == tmp_path / folder


def test_an_app_icon_elsewhere_is_not_counted_and_a_planted_frame_is(tmp_path, monkeypatch):
    home, repo = tmp_path / "home", tmp_path / "repo"
    teacher = home / "ArduinoApps" / "radio-sight-teacher" / "python"
    teacher.mkdir(parents=True)
    (teacher / "calib.json").write_text("{}")
    other = home / "ArduinoApps" / "blink-example" / "assets"
    other.mkdir(parents=True)
    plant(other / "icon.png", "png")                        # another app's icon: not the camera pipeline
    (repo / "data" / "sessions").mkdir(parents=True)
    monkeypatch.setattr(privacy, "REPO", repo)
    scan = privacy.FolderScan(privacy.default_folders({"TEACHER_APP": "user:radio-sight-teacher"}, home=home))
    assert scan.count() == 0 and scan.missing == []
    plant(repo / "data" / "sessions" / "frame.jpg", "jpeg")  # a planted frame in a data folder
    assert scan.count() == 1
    plant(teacher / "grab.jpg", "jpeg")                     # and one in the teacher's own folder
    assert scan.count() == 2


def test_without_teacher_app_its_folder_is_shown_as_not_there(tmp_path):
    scan = privacy.FolderScan(privacy.default_folders({}, home=tmp_path))
    scan.count()
    assert any("TEACHER_APP is not set" in m for m in scan.missing)


PORTS = {"nftables": [{"metainfo": {}}, {"set": {"family": "inet", "name": "out_ports", "elem": [
    {"elem": {"val": {"concat": ["udp", 53]}, "counter": {"packets": 4, "bytes": 300}}},
    {"elem": {"val": {"concat": ["udp", 123]}, "counter": {"packets": 12, "bytes": 912}}},
    {"elem": {"val": {"concat": ["tcp", 8443]}, "counter": {"packets": 1, "bytes": 60}}}]}}]}
NOPORT = {"nftables": [{"counter": {"name": "out_noport", "packets": 5, "bytes": 420}}]}


def test_explain_lists_each_port_biggest_first_with_what_it_usually_is(capsys):
    def run(cmd, **kw):
        doc = PORTS if cmd[3] == "set" else NOPORT
        return subprocess.CompletedProcess(cmd, 0, json.dumps(doc), "")
    assert privacy.explain(run=run, nft="nft") == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[1].split()[:2] == ["udp", "123"] and "time sync (NTP)" in lines[1] and "912 bytes" in lines[1]
    assert "name lookups (DNS)" in lines[2] and lines[3].split()[:2] == ["tcp", "8443"]
    assert "ping" in lines[4] and "420 bytes" in lines[4]


def test_explain_with_nothing_sent_says_nothing(capsys):
    def run(cmd, **kw):
        doc = {"nftables": [{"set": {"name": "out_ports"}}]} if cmd[3] == "set" else \
            {"nftables": [{"counter": {"bytes": 0}}]}
        return subprocess.CompletedProcess(cmd, 0, json.dumps(doc), "")
    assert privacy.explain(run=run, nft="nft") == 0
    assert capsys.readouterr().out.splitlines()[1].strip() == "nothing"


def test_explain_without_root_says_how(capsys):
    def run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", "Error: Operation not permitted")
    assert privacy.explain(run=run, nft="nft") == 1
    assert "sudo" in capsys.readouterr().err


def test_container_files_are_counted_from_dockers_changes():
    replies = {"/containers/json": [{"Id": "abc"}],
               "/containers/abc/changes": [{"Path": "/tmp/frame.jpg", "Kind": 1},
                                           {"Path": "/app/out.mp4", "Kind": 0},
                                           {"Path": "/tmp/gone.png", "Kind": 2},
                                           {"Path": "/tmp/labels.json", "Kind": 1},
                                           {"Path": "/usr/lib/python3/site-packages/a.png", "Kind": 1}]}
    scan = privacy.ContainerScan(get=replies.get)
    assert scan.count() == 2 and scan.containers == 1


def test_no_docker_on_this_machine_means_no_containers():
    scan = privacy.ContainerScan(get=lambda path: None)
    assert scan.count() == 0 and scan.containers == 0


# ---- bytes out ----

def nft_run(stdout="", returncode=0, stderr=""):
    def run(cmd, **kw):
        assert cmd[1:] == ["-j", "list", "counter", "inet", "radio_sight_privacy", "out"]
        return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)
    return run


def test_nft_counter_reads_the_byte_count():
    out = json.dumps({"nftables": [{"metainfo": {"version": "1.1.3"}},
                                   {"counter": {"family": "inet", "name": "out", "packets": 3, "bytes": 252}}]})
    assert privacy.NftCounter("nft", run=nft_run(out)).read() == 252


@pytest.mark.parametrize("kw, why", [
    ({"returncode": 1, "stderr": "Error: Could not process rule: Operation not permitted"}, "permission"),
    ({"returncode": 1, "stderr": "Error: No such file or directory"}, "isn't loaded"),
    ({"stdout": '{"nftables": [{"metainfo": {}}]}'}, "no byte count"),
    ({"stdout": "garbage"}, "no byte count"),
])
def test_nft_trouble_is_unreadable_never_zero(kw, why):
    with pytest.raises(privacy.Unreadable, match=why):
        privacy.NftCounter("nft", run=nft_run(**kw)).read()


def test_nft_missing_says_how_to_install_it():
    def run(cmd, **kw):
        raise FileNotFoundError(cmd[0])
    with pytest.raises(privacy.Unreadable, match="apt install nftables"):
        privacy.NftCounter("nft", run=run).read()


# ---- the meter ----

def test_a_clean_board_reads_zero_and_zero(meter):
    m = meter()
    doc = m.tick()
    assert (doc["ok"], doc["images"], doc["bytes_out"]) == (True, 0, 0)
    assert doc["since_t"] == doc["t"] == 1_763_149_500_000
    assert json.loads((m.run_dir / "status.json").read_text())["ok"] is True


def test_bytes_to_the_internet_make_it_go_up(meter):
    counter, clock = FakeCounter(), Clock()
    m = meter(counter, clock=clock)
    m.tick()
    counter.value, clock.t = 1480, clock.t + 1
    assert m.tick()["bytes_out"] == 1480


def test_on_a_new_boot_everything_the_kernel_counted_is_kept(meter):
    assert meter(FakeCounter(900)).tick()["bytes_out"] == 900


def test_a_stored_image_is_counted_live(meter, folders):
    m = meter(containers=FakeContainers(1))
    plant(folders[0] / "leak.png", "png")
    assert m.tick()["images"] == 2


@pytest.mark.parametrize("broken", ["counter", "containers"])
def test_anything_unreadable_means_ok_false_and_no_numbers(meter, broken):
    counter, containers = FakeCounter(), FakeContainers()
    (counter if broken == "counter" else containers).why = "can't read it"
    doc = meter(counter, containers).tick()
    assert doc["ok"] is False and doc["why"] == "can't read it"
    assert not {"images", "bytes_out", "since_t"} & set(doc)


def test_a_restart_of_the_meter_keeps_the_count_and_since(meter):
    counter, clock = FakeCounter(100), Clock()
    first = meter(counter, clock=clock).tick()
    counter.value, clock.t = 600, clock.t + 30
    again = meter(counter, clock=clock).tick()
    assert again["bytes_out"] == 600 and again["since_t"] == first["since_t"]


def test_a_counter_that_went_down_while_the_meter_was_off_starts_over(meter):
    counter, clock = FakeCounter(500), Clock()
    meter(counter, clock=clock).tick()
    counter.value, clock.t = 30, clock.t + 9
    doc = meter(counter, clock=clock).tick()
    assert doc["bytes_out"] == 30 and doc["since_t"] == int(clock.t * 1000)


def test_a_reboot_starts_over_and_says_so(meter):
    counter, clock = FakeCounter(500), Clock()
    meter(counter, clock=clock).tick()
    counter.value, clock.t = 40, clock.t + 60
    m = meter(counter, clock=clock, boot="boot-2")
    doc = m.tick()
    assert doc["bytes_out"] == 40 and doc["since_t"] == int(clock.t * 1000)
    assert any("started on this boot" in line for line in m.logged)


def test_a_counter_that_goes_down_starts_over_instead_of_going_negative(meter):
    counter, clock = FakeCounter(500), Clock()
    m = meter(counter, clock=clock)
    m.tick()
    counter.value, clock.t = 20, clock.t + 5
    doc = m.tick()
    assert doc["bytes_out"] == 20 and doc["since_t"] == int(clock.t * 1000)
    assert any("went down" in line for line in m.logged)


def test_reset_is_an_operator_action_logged_with_the_time(meter):
    counter, clock = FakeCounter(), Clock()
    m = meter(counter, clock=clock)
    m.tick()
    counter.value, clock.t = 3000, clock.t + 10
    assert m.tick()["bytes_out"] == 3000  # no reset without the request
    (m.run_dir / "reset").write_text("asked")
    counter.value, clock.t = 3100, clock.t + 1
    doc = m.tick()
    assert doc["bytes_out"] == 0 and doc["since_t"] == int(clock.t * 1000)
    assert not (m.run_dir / "reset").exists()
    log = (m.state_dir / "resets.log").read_text()
    assert "reset by the operator: it was 3100 bytes out" in log and log[:4] == "2025"
    counter.value = 3150
    assert m.tick()["bytes_out"] == 50


# ---- reading it back ----

def write_status(tmp_path, **doc):
    p = tmp_path / "status.json"
    p.write_text(json.dumps(doc))
    return p


def test_status_serves_only_the_contract_fields(tmp_path):
    p = write_status(tmp_path, ok=True, images=0, bytes_out=12, since_t=1000, t=5000, missing=[], folders=3,
                     containers=1)
    assert privacy.status(p, now_ms=5500) == {"ok": True, "images": 0, "bytes_out": 12, "since_t": 1000, "t": 5000}


def test_no_status_file_means_not_running(tmp_path):
    assert privacy.status(tmp_path / "none.json") == {"ok": False, "why": "privacy meter is not running"}


def test_an_old_reading_is_not_served_as_current(tmp_path):
    p = write_status(tmp_path, ok=True, images=0, bytes_out=0, since_t=1000, t=5000)
    doc = privacy.status(p, now_ms=8001)
    assert doc["ok"] is False and "stopped updating" in doc["why"] and "bytes_out" not in doc


@pytest.mark.parametrize("doc", [
    {"ok": True, "images": None, "bytes_out": 0, "since_t": 1, "t": 5000},
    {"ok": True, "bytes_out": 0, "since_t": 1, "t": 5000},
    {"ok": True, "images": 0, "bytes_out": -1, "since_t": 1, "t": 5000},
    {"ok": True, "images": True, "bytes_out": 0, "since_t": 1, "t": 5000},
    {"ok": "yes", "images": 0, "bytes_out": 0, "since_t": 1, "t": 5000},
    {"ok": True, "images": 0, "bytes_out": 0, "since_t": 1},
])
def test_a_reading_with_a_missing_or_bad_number_is_never_ok(tmp_path, doc):
    p = write_status(tmp_path, **doc)
    assert privacy.status(p, now_ms=5000)["ok"] is False


def test_a_garbled_status_file_is_not_ok(tmp_path):
    p = tmp_path / "status.json"
    p.write_text("{not json")
    assert privacy.status(p)["ok"] is False


def test_the_meters_own_why_is_passed_on(tmp_path):
    p = write_status(tmp_path, ok=False, why="nft is not installed", t=5000)
    assert privacy.status(p, now_ms=5000) == {"ok": False, "why": "nft is not installed"}


def test_one_line_a_person_can_read():
    doc = {"ok": True, "images": 0, "bytes_out": 0, "since_t": 1_000_000, "t": 1_000_000 + 754_000,
           "folders": 3, "missing": ["/home/x/ArduinoApps"], "containers": 1}
    text = privacy.line(doc)
    assert text.startswith("0 images stored, 0 bytes sent out, counting for 12 min (since ")
    assert "checked 2 folders and 1 containers; not there: /home/x/ArduinoApps" in text
    assert "\n" not in text
    assert privacy.line({"ok": False, "why": "privacy meter is not running"}) == "privacy meter not running"
    assert privacy.line({"ok": False, "why": "nft is not installed"}) == "privacy meter can't count: nft is not installed"


def test_the_command_prints_one_line_and_fails_when_not_running(tmp_path, capsys):
    assert privacy.main(["--status", str(tmp_path / "none.json")]) == 1
    assert capsys.readouterr().out.strip() == "privacy meter not running"


def test_reset_command_waits_for_the_meter_to_take_it(meter, monkeypatch):
    clock = Clock()
    m = meter(FakeCounter(77), clock=clock)
    m.tick()
    status = m.run_dir / "status.json"
    monkeypatch.setattr(privacy, "_ms", lambda c=None: int(clock.t * 1000))

    def sleep(s):
        clock.t += 1
        m.tick()

    assert privacy.reset(status, clock=clock, sleep=sleep) == 0
    assert privacy.status(status, now_ms=int(clock.t * 1000))["bytes_out"] == 0


def test_reset_without_a_running_meter_resets_nothing(tmp_path):
    assert privacy.reset(tmp_path / "none.json") == 1
    assert not (tmp_path / "reset").exists()


# ---- GET /privacy ----

@pytest.fixture
def server(tmp_path):
    srv = serve.make_server("127.0.0.1", 0, dist=tmp_path, nodes=tmp_path / "n.json", proof=tmp_path / "p.json",
                            privacy_path=tmp_path / "status.json")
    threading.Thread(target=srv.serve_forever, args=(0.05,), daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/privacy", tmp_path / "status.json"
    srv.shutdown()
    srv.server_close()


def fetch(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.headers["Content-Type"], json.loads(r.read())


def test_get_privacy_when_the_meter_is_not_running(server):
    url, _ = server
    assert fetch(url) == (200, "application/json", {"ok": False, "why": "privacy meter is not running"})


def test_get_privacy_serves_the_live_reading(server, tmp_path, meter):
    url, _ = server
    m = meter(FakeCounter(64), clock=__import__("time").time)
    m.run_dir = tmp_path  # the server's status file
    m.tick()
    status, _, doc = fetch(url)
    assert status == 200 and doc["ok"] is True and (doc["images"], doc["bytes_out"]) == (0, 64)
    assert set(doc) == {"ok", "images", "bytes_out", "since_t", "t"}
