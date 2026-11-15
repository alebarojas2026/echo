"""A full disk when a baseline finishes (#588): baseline_done still goes out and no file is cut short."""
import json
import logging
from pathlib import Path

from brain.core import Brain
from brain.tests.simdata import T0_MS


def capture(brain, seconds=26, at=None, start_s=0):
    """10 Hz of cam, an empty label and one reading per link. at(s) runs before each tick."""
    kinds = []
    seq = 0
    for i in range(seconds * 10):
        s, t = i / 10, T0_MS + start_s * 1000 + i * 100
        if at:
            at(s)
        msgs = [{"type": "cam", "state": "on", "fps": 9},
                {"type": "label", "frame": i, "mode": "off", "persons_in_frame": 0, "present": False, "zone": 0,
                 "foot_m": None, "motion": None, "conf": 0.9, "clipped": False}]
        msgs += [{"type": "rssi", "link": link, "kind": link.split(":")[1], "tx": link.split(">")[0],
                  "rx": link.split(">")[1].split(":")[0], "dbm": -55} for link in brain.links]
        for m in msgs:
            seq += 1
            brain.on_message({"v": 2, "t": t, "seq": seq, "src": "sim", "recv_t": t, **m})
        brain.state()
        kinds += [e["kind"] for e in brain.pop_events()]
    return kinds


def baseline(tmp_path):
    brain = Brain(sessions_dir=tmp_path)
    brain.on_cmd({"v": 2, "type": "cmd", "cmd": "baseline", "args": {}})
    return brain


def full_disk(monkeypatch):
    """Every write of a file's text fails from now on, as on a full disk."""
    def no_space(self, *args, **kwargs):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(Path, "write_text", no_space)


def test_baseline_done_still_goes_out_when_the_disk_is_full(tmp_path, monkeypatch, caplog):
    brain = baseline(tmp_path)
    with caplog.at_level(logging.WARNING, logger="brain"):
        kinds = capture(brain, at=lambda s: full_disk(monkeypatch) if s == 15 else None)
    assert kinds.count("baseline_done") == 1 and brain.capture is None
    assert len(brain.base) == len(brain.links)                     # in use, as the screen was told
    assert any("could not save the baseline" in r.getMessage() for r in caplog.records)
    assert not list(tmp_path.glob("*.tmp"))


def test_an_older_baseline_file_is_left_whole_not_cut_short(tmp_path, monkeypatch):
    first = baseline(tmp_path)
    capture(first)
    before = (tmp_path / "baseline.json").read_text()
    assert json.loads(before)["links"] and json.loads((tmp_path / "place.json").read_text())["t"]

    second = Brain(sessions_dir=tmp_path)
    second.on_cmd({"v": 2, "type": "cmd", "cmd": "baseline", "args": {"keep_model": True}})
    full_disk(monkeypatch)
    kinds = capture(second)
    assert "baseline_done" in kinds
    monkeypatch.undo()
    assert (tmp_path / "baseline.json").read_text() == before      # whole, not 1 byte
    assert Brain(sessions_dir=tmp_path).base                       # so a restart still has a baseline


def test_recalibrating_is_cleared_when_the_save_fails(tmp_path, monkeypatch):
    brain = baseline(tmp_path)
    capture(brain)
    brain.recalibrating, brain._old_base = True, dict(brain.base)
    brain._start_capture(new_place=False, by_hand=False)           # the automatic one after router_home
    full_disk(monkeypatch)
    kinds = capture(brain, start_s=30)
    assert "baseline_done" in kinds and brain.recalibrating is False


def test_files_are_written_through_a_temporary_file(tmp_path):
    brain = baseline(tmp_path)
    capture(brain)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert "baseline.json" in names and "place.json" in names and "baselines.jsonl" in names
    assert not [n for n in names if n.endswith(".tmp")]
    assert json.loads((tmp_path / "baseline.json").read_text())["links"]
