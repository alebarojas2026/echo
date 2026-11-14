"""Host command to mounted mode-file to fake processed-frame label."""

import json
import socket
import time

import pytest

from teacher.applab.python.labels import Projection, Teacher, attach_processed_results, read_mode


def test_screen_command_reaches_fake_teacher_within_one_second(tmp_path):
    core = pytest.importorskip("brain.core")
    mode_file = tmp_path / "label_mode"
    brain = core.Brain(mode_file=str(mode_file))
    projection = Projection({"image_size": [400, 400], "homography": [[0.01, 0, -1], [0, -0.01, 3], [0, 0, 1]]})
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rx, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tx:
        rx.bind(("127.0.0.1", 0))
        rx.settimeout(1)
        def send(label):
            tx.sendto(json.dumps(label).encode(), rx.getsockname())
        teacher = Teacher(projection, send, mode=lambda: read_mode(mode_file))
        for mode in ("off", "person", "object", "off"):
            started = time.monotonic()
            brain.on_cmd({"v": 2, "type": "cmd", "cmd": "label_mode", "args": {"mode": mode}})
            teacher.processed([])  # fake brick's explicit processed empty frame
            message = json.loads(rx.recv(65535))
            assert message["mode"] == mode
            assert time.monotonic() - started < 1
            assert message["zone"] == 0 and message["motion"] is None


def test_missing_mount_recovers_after_host_writes_mode(tmp_path):
    core = pytest.importorskip("brain.core")
    path = tmp_path / "label_mode"
    sent = []
    projection = Projection({"image_size": [400, 400], "homography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]})
    class FakeBrick:
        calls = 0
        def _process_message(self, ws, message):
            self.calls += 1
    brick = FakeBrick()
    attach_processed_results(brick, Teacher(projection, sent.append, mode=lambda: read_mode(path)))
    message = json.dumps({"type": "classification", "result": {"bounding_boxes": []}})
    brick._process_message(None, message)
    assert not sent
    core.Brain(mode_file=str(path)).on_cmd({"v": 2, "type": "cmd", "cmd": "label_mode", "args": {"mode": "person"}})
    brick._process_message(None, message)
    assert sent[-1]["mode"] == "person" and brick.calls == 2
