"""A full disk during a recording (#527): the recording stops, the bus and the brain's feed don't."""
import json
import logging

from bus.core import Bus, Recorder

RSSI = {"v": 2, "type": "rssi", "t": 1, "seq": 1, "src": "live", "link": "east>pi5:ble", "kind": "ble",
        "tx": "east", "rx": "pi5", "dbm": -60}
START = {"v": 2, "type": "cmd", "t": 1, "seq": 1, "src": "live", "cmd": "record_start",
         "args": {"session": "s1", "purpose": "train", "walker": "w"}}


class FullDisk:
    """A file whose writes start failing, like a disk that filled up."""

    def __init__(self, real, after):
        self.real, self.after, self.closed = real, after, False

    def write(self, text):
        if self.after <= 0:
            raise OSError(28, "No space left on device")
        self.after -= 1
        return self.real.write(text)

    def flush(self):
        if self.after <= 0:
            raise OSError(28, "No space left on device")
        return self.real.flush()

    def close(self):
        self.closed = True
        self.real.close()
        raise OSError(28, "No space left on device")   # the last flush on close fails too


def send(bus, seq):
    return bus.handle(json.dumps(dict(RSSI, seq=seq)).encode(), ("127.0.0.1", 2))


def test_a_full_disk_stops_the_recording_and_forwarding_goes_on(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="bus")
    sent = []
    bus = Bus(sessions=tmp_path, send=sent.append, clock=lambda: 1000)
    bus.handle(json.dumps(START).encode(), ("127.0.0.1", 1))
    send(bus, 1)
    bus.recorder._file = FullDisk(bus.recorder._file, after=0)
    for seq in range(2, 12):
        assert send(bus, seq) is not None                  # never raises
    assert [json.loads(m)["seq"] for m in sent if json.loads(m)["type"] == "rssi"] == list(range(1, 12))
    assert not bus.recorder.recording
    assert not (tmp_path / ".open").exists()               # a restarted bus won't pick it up and fail again
    said = [r.getMessage() for r in caplog.records if "stopped" in r.getMessage()]
    assert len(said) == 1 and "recording s1 stopped after 2 lines" in said[0] and "keeps forwarding" in said[0]
    lines = (tmp_path / "s1.jsonl").read_text().splitlines()
    assert [json.loads(line)["type"] for line in lines] == ["meta", "rssi"]   # what was written stays
    bus.close()                                            # and closing doesn't raise either


def test_a_restarted_bus_on_a_full_disk_doesnt_crash_loop(tmp_path):
    # The mark from a recording that was open when the disk filled: the new bus resumes it, the
    # first write fails, and it carries on forwarding.
    first = Bus(sessions=tmp_path, clock=lambda: 1000)
    first.handle(json.dumps(START).encode(), ("127.0.0.1", 1))
    first.close()
    sent = []
    bus = Bus(sessions=tmp_path, send=sent.append, clock=lambda: 2000)
    assert bus.recorder.recording
    bus.recorder._file = FullDisk(bus.recorder._file, after=0)
    send(bus, 1)
    send(bus, 2)
    assert len(sent) == 2 and not bus.recorder.recording and not (tmp_path / ".open").exists()
    bus.close()


def test_a_recording_that_cant_be_opened_records_nothing_and_forwards(tmp_path, monkeypatch, caplog):
    def refuse(self, session, meta):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Recorder, "start", refuse)
    sent = []
    bus = Bus(sessions=tmp_path, send=sent.append, clock=lambda: 1000)
    bus.handle(json.dumps(START).encode(), ("127.0.0.1", 1))
    send(bus, 1)
    assert not bus.recorder.recording
    assert [json.loads(m)["type"] for m in sent] == ["meta", "rssi"]
    assert any("can't open the recording" in r.getMessage() for r in caplog.records)
    bus.close()
