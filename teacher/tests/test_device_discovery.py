from teacher.camwatch import Watcher, discover_device


def test_no_usb_by_id_means_no_camera(tmp_path):
    (tmp_path / "platform-board-video-index0").touch()
    (tmp_path / "usb-Camera-video-index1").touch()
    assert discover_device(directory=tmp_path) is None


def test_existing_usb_capture_and_override(tmp_path):
    camera = tmp_path / "usb-Logitech_BRIO-video-index0"
    camera.touch()
    assert discover_device(directory=tmp_path) == camera
    override = tmp_path / "explicit-device"
    assert discover_device(override, tmp_path) == override


def test_dangling_entries_do_not_prove_presence(tmp_path):
    (tmp_path / "usb-Logitech_BRIO-video-index0").symlink_to(tmp_path / "unplugged")
    assert discover_device(directory=tmp_path) is None


def test_unplug_replug_changes_within_poll_interval(tmp_path):
    camera = tmp_path / "usb-Logitech_BRIO-video-index0"
    sent = []
    watcher = Watcher(sent.append, lambda _: None)
    def poll(t, heartbeat=None):
        path = discover_device(directory=tmp_path)
        watcher.tick(t, path is not None and path.exists(), heartbeat)
    poll(0)
    assert sent[-1]["state"] == "off"
    camera.touch()
    poll(50, {"t": 50, "frame": 1})
    assert sent[-1]["state"] == "on"
    camera.unlink()
    poll(100)
    assert sent[-1]["state"] == "off"
    camera.touch()
    poll(150, {"t": 150, "frame": 2})
    assert sent[-1]["state"] == "on"
