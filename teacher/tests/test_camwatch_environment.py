import json

import pytest

from teacher.camwatch import main


class StopPolling(Exception):
    pass


@pytest.mark.parametrize("override", [False, True])
def test_bare_service_entrypoint_uses_environment(tmp_path, monkeypatch, override):
    messages, actions = [], []
    monkeypatch.setenv("TEACHER_APP", "user:teacher")
    monkeypatch.setenv("TEACHER_HEARTBEAT", str(tmp_path / "heartbeat.json"))
    monkeypatch.setenv("TEACHER_DEVICE", str(tmp_path / "absent-camera"))
    class FakeSocket:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def sendto(self, data, destination): messages.append((json.loads(data), destination))
    class FakeWorker:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def submit(self, function, app, action): actions.append((app, action))
    monkeypatch.setattr("teacher.camwatch.socket.socket", lambda *args: FakeSocket())
    monkeypatch.setattr("teacher.camwatch.ThreadPoolExecutor", FakeWorker)
    def stop(_): raise StopPolling()
    monkeypatch.setattr("teacher.camwatch.time.sleep", stop)
    with pytest.raises(StopPolling):
        main(["--app", "user:override"] if override else [])
    assert messages[0][1] == ("127.0.0.1", 5600)
    assert messages[0][0]["state"] == "off" and messages[0][0]["v"] == 2
    assert actions == [("user:override" if override else "user:teacher", "stop")]


def test_missing_environment_reports_configuration_keys(monkeypatch, capsys):
    monkeypatch.delenv("TEACHER_APP", raising=False)
    monkeypatch.delenv("TEACHER_HEARTBEAT", raising=False)
    with pytest.raises(SystemExit) as error:
        main([])
    assert error.value.code == 2
    assert "TEACHER_APP" in capsys.readouterr().err
