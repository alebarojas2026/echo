"""A fit reads the newest few recordings of each kind, so it doesn't grow with every judge (#611)."""
import json

from brain.core import TRAIN_KEEP, Brain


def place(tmp_path):
    brain = Brain(sessions_dir=tmp_path)
    brain._set_baseline({link: -50.0 for link in brain.links}, {link: 15.0 for link in brain.links})
    brain.place_t = 1_000_000
    brain.spawn = lambda fit, done: None            # don't fit: look at what the next fit would read
    return brain


def record(tmp_path, name, t, purpose="train", walker="judge"):
    (tmp_path / f"{name}.jsonl").write_text(json.dumps(
        {"v": 2, "type": "meta", "t": 0, "seq": 1, "src": "sim", "session": name, "purpose": purpose,
         "walker": walker, "recv_t": t}) + "\n")


def next_fit(brain):
    brain.training = None
    brain.on_cmd({"v": 2, "type": "cmd", "cmd": "train", "args": {}})
    return brain.training["sessions"]


def test_forty_lessons_in_one_place_fit_on_the_newest_few(tmp_path):
    brain = place(tmp_path)
    sizes = []
    for judge in range(40):                         # every judge's lesson leaves one train recording
        record(tmp_path, f"v{judge:02d}-lesson", 2_000_000 + judge)
        sizes.append(len(next_fit(brain)))
    assert max(sizes) == TRAIN_KEEP and sizes[-1] == TRAIN_KEEP          # flat, not 40
    assert next_fit(brain) == [f"v{j:02d}-lesson" for j in range(40 - TRAIN_KEEP, 40)]   # the newest ones


def test_lessons_never_push_out_the_empty_room_or_the_tray(tmp_path):
    brain = place(tmp_path)
    record(tmp_path, "empty1", 1_500_000, walker=None)
    record(tmp_path, "empty2", 1_500_001, walker="  ")                   # a blank id is no walker
    record(tmp_path, "tray1", 1_500_002, purpose="object", walker="w1")
    for judge in range(TRAIN_KEEP + 5):
        record(tmp_path, f"v{judge:02d}", 2_000_000 + judge)
    got = next_fit(brain)
    assert {"empty1", "empty2", "tray1"} <= set(got)
    assert len(got) == TRAIN_KEEP + 3 and f"v{TRAIN_KEEP + 4:02d}" in got and "v00" not in got


def test_each_kind_is_capped_on_its_own(tmp_path):
    brain = place(tmp_path)
    n = TRAIN_KEEP + 3
    for i in range(n):
        record(tmp_path, f"e{i:02d}", 1_500_000 + i, walker=None)
        record(tmp_path, f"t{i:02d}", 1_600_000 + i, purpose="object", walker=None)
    got = next_fit(brain)
    assert got == sorted([f"e{i:02d}" for i in range(3, n)] + [f"t{i:02d}" for i in range(3, n)])


def test_a_few_recordings_are_all_used(tmp_path):
    brain = place(tmp_path)
    record(tmp_path, "a", 2_000_000)
    record(tmp_path, "b", 2_000_001)
    assert next_fit(brain) == ["a", "b"]
    assert sorted(p.name for p in tmp_path.glob("*.jsonl")) == ["a.jsonl", "b.jsonl"]   # nothing is deleted
