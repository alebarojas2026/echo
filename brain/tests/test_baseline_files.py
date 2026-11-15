"""baseline.json and place.json are written whole or not at all (#588): a full disk, or power
pulled in the middle of a write, never leaves a cut-off file, and baseline_done is sent either way."""
import json
import os

import brain.core as core
from brain.core import Brain
from brain.tests.test_core import Feed, cmd


def baselined(tmp_path):
    brain = Brain(sessions_dir=tmp_path)
    feed = Feed(brain)
    brain.on_cmd(cmd("baseline"))
    feed.play("empty_room", seed=1)
    assert any(e["kind"] == "baseline_done" for e in brain.pop_events())
    return brain, feed


def test_both_files_are_written_through_a_temporary_file_and_none_is_left_behind(tmp_path, monkeypatch):
    moved = []
    real = os.replace
    monkeypatch.setattr(core.os, "replace", lambda a, b: (moved.append((str(a), str(b))), real(a, b))[1])
    brain, _ = baselined(tmp_path)
    names = [(os.path.basename(a), os.path.basename(b)) for a, b in moved]
    assert ("place.json.tmp", "place.json") in names and ("baseline.json.tmp", "baseline.json") in names
    assert names.index(("place.json.tmp", "place.json")) < names.index(("baseline.json.tmp", "baseline.json"))
    assert not list(tmp_path.glob("*.tmp"))
    assert json.loads((tmp_path / "place.json").read_text())["t"] == brain.place_t
    assert Brain(sessions_dir=tmp_path).base == brain.base


def test_a_write_that_dies_half_way_leaves_the_old_files_as_they_were(tmp_path, monkeypatch, caplog):
    brain, feed = baselined(tmp_path)
    before = {n: (tmp_path / n).read_text() for n in ("baseline.json", "place.json")}

    def cut(a, b):   # the power goes (or the disk fills) before the rename
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(core.os, "replace", cut)
    brain.on_cmd(cmd("baseline"))
    with caplog.at_level("WARNING", logger="brain"):
        feed.play("empty_room", seed=2)
    kinds = [e["kind"] for e in brain.pop_events()]
    assert "baseline_done" in kinds                       # the operator is told: the baseline is in use
    assert brain.capture is None and brain.base
    assert "could not save the baseline" in caplog.text
    assert {n: (tmp_path / n).read_text() for n in before} == before
    again = Brain(sessions_dir=tmp_path)                  # a restart finds the last baseline that was saved whole
    saved = json.loads(before["baseline.json"])["links"]
    assert again.base == {k: v["base_dbm"] for k, v in saved.items()}
    assert again.place_t == json.loads(before["place.json"])["t"]


def test_a_full_disk_during_the_automatic_baseline_still_ends_recalibrating(tmp_path, monkeypatch):
    brain, feed = baselined(tmp_path)
    brain.recalibrating, brain._old_base = True, dict(brain.base)
    brain._start_capture(new_place=False, by_hand=False)
    monkeypatch.setattr(core.Brain, "_write_baseline",
                        lambda self, now: (_ for _ in ()).throw(OSError(28, "No space left on device")))
    feed.play("empty_room", seed=3)
    assert "baseline_done" in [e["kind"] for e in brain.pop_events()]
    assert brain.recalibrating is False
