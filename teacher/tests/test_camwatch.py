import json

from teacher.camwatch import Watcher, read_heartbeat, run_action
from teacher.applab.python.heartbeat import write_heartbeat


def test_unplug_replug_delay_and_changed_state():
    sent, actions = [], []
    watcher = Watcher(sent.append, actions.append)
    watcher.tick(0, False)
    assert actions == ["stop"] and sent[-1]["state"] == "off"
    watcher.tick(100, True)
    assert sent[-1]["state"] == "stalled"
    watcher.tick(2099, True)
    assert actions == ["stop"]
    watcher.tick(2100, True)
    assert actions == ["stop", "start"]
    watcher.tick(2200, True, dict(t=2200, frame=1))
    assert sent[-1]["state"] == "on"
    watcher.tick(2300, True, dict(t=2300, frame=2))
    watcher.tick(3200, True, dict(t=3200, frame=11))
    assert sent[-1]["fps"] == 10
    watcher.tick(4199, True, dict(t=3200, frame=11))
    assert watcher.state == "on"
    watcher.tick(4200, True, dict(t=3200, frame=11))
    assert sent[-1]["state"] == "stalled" and sent[-1]["fps"] == 0
    watcher.tick(5250, False)
    assert sent[-1]["state"] == "off" and actions[-1] == "stop"
    assert [m["seq"] for m in sent] == list(range(1, len(sent) + 1))
    assert all(m["v"] == 2 and m["type"] == "cam" for m in sent)


def test_periodic_messages_and_stale_replug_heartbeat():
    sent = []
    watcher = Watcher(sent.append, lambda _: None)
    watcher.tick(0, False)
    watcher.tick(999, False)
    assert len(sent) == 1
    watcher.tick(1000, False)
    assert len(sent) == 2
    watcher.tick(1100, True, dict(t=500, frame=100))
    assert sent[-1]["state"] == "stalled"
    watcher.tick(1200, True, dict(t=5000, frame=100))
    assert sent[-1]["state"] == "stalled"


def test_numeric_heartbeat_atomic_and_missing(tmp_path):
    path = tmp_path / "heartbeat.json"
    assert read_heartbeat(path) is None
    write_heartbeat(path, {"t": 1000, "frame": 4, "unrelated": "not persisted"})
    assert json.loads(path.read_text()) == {"t": 1000, "frame": 4}
    assert len(list(tmp_path.iterdir())) == 1
    path.write_text("broken")
    assert read_heartbeat(path) is None


def test_cli_uses_argument_list(monkeypatch):
    calls = []
    monkeypatch.setattr("teacher.camwatch.subprocess.run", lambda argv, **kw: calls.append((argv, kw)))
    run_action("user:radio-sight-teacher", "stop")
    assert calls[0][0] == ["arduino-app-cli", "app", "stop", "user:radio-sight-teacher"]
    assert calls[0][1]["check"] is True
