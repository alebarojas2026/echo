"""The scan for this place's recordings doesn't re-read files it has already looked at (#648)."""
import json

import brain.core as core
from brain.core import Brain


def write(folder, name, purpose, t, extra=()):
    lines = [{"v": 2, "type": "meta", "session": name, "purpose": purpose, "walker": "w1", "recv_t": t}, *extra]
    (folder / f"{name}.jsonl").write_text("".join(json.dumps(m) + "\n" for m in lines))


def counting(monkeypatch):
    opened = []
    real = core.last_meta
    monkeypatch.setattr(core, "last_meta", lambda path: (opened.append(path.stem), real(path))[1])
    return opened


def test_200_demo_recordings_are_read_once_not_at_every_fit(tmp_path, monkeypatch):
    brain = Brain(sessions_dir=tmp_path)
    brain.place_t = 1_000
    for i in range(200):
        write(tmp_path, f"demo{i:03d}", "demo", 2_000 + i)
    write(tmp_path, "t1", "train", 3_000)
    opened = counting(monkeypatch)
    brain._find_sessions()
    assert len(opened) == 201 and list(brain.sessions) == ["t1"]
    del opened[:]
    brain._find_sessions()                              # the next fit, 15 s later
    assert opened == []                                 # none of them is opened again


def test_a_file_that_changed_is_read_again(tmp_path, monkeypatch):
    brain = Brain(sessions_dir=tmp_path)
    brain.place_t = 1_000
    write(tmp_path, "s5", "demo", 2_000)
    opened = counting(monkeypatch)
    brain._find_sessions()
    assert opened == ["s5"] and brain.sessions == {}
    # The same name is recorded again, this time as a training walk: the file grows.
    with open(tmp_path / "s5.jsonl", "a") as f:
        f.write(json.dumps({"v": 2, "type": "meta", "session": "s5", "purpose": "train", "walker": "w2",
                            "recv_t": 5_000}) + "\n")
    brain._find_sessions()
    assert opened == ["s5", "s5"] and list(brain.sessions) == ["s5"]


def test_a_new_place_looks_at_the_files_again(tmp_path, monkeypatch):
    brain = Brain(sessions_dir=tmp_path)
    brain.place_t = 1_000
    write(tmp_path, "old", "train", 500)                # recorded before this place began
    opened = counting(monkeypatch)
    brain._find_sessions()
    brain._find_sessions()
    assert opened == ["old"] and brain.sessions == {}
    brain.place_t = 400                                 # (a test's way of asking: what if the cut-off moved)
    brain._find_sessions()
    assert opened == ["old", "old"] and list(brain.sessions) == ["old"]
