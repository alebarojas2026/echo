"""The sweep's rules: sealing, refusals, the tables. SIMULATED sessions only."""
import json
import shutil
from pathlib import Path

import pytest

from lab import sweep_core as C
from lab import sweep_report as R
from lab import sweep_sim

TINY = {"window_ms": [1000], "features": ["absolute"], "forest": [[10, 6]], "links": ["all", "router_receiver"],
        "lesson_s": [None], "smooth": [[10, 6]], "moving_run": [5], "unsure_p": [0.0, 0.55]}
PLAN = [("t-w1", "train", "w1", 0), ("t-w2", "train", "w2", 0), ("t-w3", "train", "w3", 0),
        ("t-empty", "train", None, 0), ("h-w4", "heldout", "w4", 0)]


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    return sweep_sim.make(tmp_path_factory.mktemp("sim"), C.REPO / "radio" / "nodes.json", plan=PLAN)


@pytest.fixture
def folder(made, tmp_path):
    dst = tmp_path / "sessions"
    shutil.copytree(made, dst)
    return dst


class Spy:
    """Stands in for Modal: runs the jobs here and remembers what it was given."""

    def __init__(self):
        self.blobs, self.heldout_calls = [], []

    def map_jobs(self, blob, jobs, posts):
        self.blobs.append(blob)
        return R.local_map(blob, jobs, posts, n_jobs=1)

    def score(self, train_blob, sealed_blob, settings):
        self.heldout_calls.append(C.unpack(sealed_blob))
        return C.score_heldout(train_blob, sealed_blob, settings, n_jobs=1)


def _rewrite(path: Path, change):
    lines = [json.loads(l) for l in path.read_text().splitlines()]
    path.write_text("".join(json.dumps(change(m), separators=(",", ":")) + "\n" for m in lines))


def test_heldout_sessions_are_sealed_and_never_in_a_tuning_payload(folder, tmp_path):
    data = C.load_folder(folder)
    tune, sealed, _ = C.split(data, C.Ledger(tmp_path / "sealed.json"), "now")
    assert sealed.ids == ["h-w4"]
    assert all(s["purpose"] == "train" for s in tune)
    doc = C.unpack(C.payload(tune, data["layout"], sealed=sealed.hashes))
    assert {s["id"] for s in doc["sessions"]} == {"t-w1", "t-w2", "t-w3", "t-empty"}
    assert not {s["hash"] for s in doc["sessions"]} & sealed.hashes
    held = [s for s in data["sessions"] if s["purpose"] == "heldout"]
    with pytest.raises(C.Refused):
        C.payload(held, data["layout"])
    with pytest.raises(C.Refused):
        C.assert_tunable(tune + held)


def test_a_renamed_heldout_recording_is_refused_for_tuning(folder, tmp_path):
    ledger = C.Ledger(tmp_path / "sealed.json")
    C.split(C.load_folder(folder), ledger, "now")
    ledger.save()
    # Someone copies the held-out walk and relabels it as training.
    copy = folder / "t-sneaky.jsonl"
    shutil.copyfile(folder / "h-w4.jsonl", copy)
    _rewrite(copy, lambda m: dict(m, purpose="train", session="t-sneaky") if m["type"] == "meta" else m)
    (folder / "h-w4.jsonl").unlink()
    with pytest.raises(C.Refused, match="sealed held-out"):
        C.split(C.load_folder(folder), C.Ledger(tmp_path / "sealed.json"), "later")


def test_heldout_content_cannot_change_the_tuning(folder, tmp_path):
    """Whatever the held-out recording holds, tuning sees the same bytes and picks the same winner;
    the held-out readings are opened once, after the winner is picked."""
    a = Spy()
    rep_a = R.run(folder, a.map_jobs, a.score, out=tmp_path / "a", grid=TINY)
    _rewrite(folder / "h-w4.jsonl", lambda m: dict(m, dbm=m["dbm"] - 20) if m["type"] == "rssi" else m)
    b = Spy()
    rep_b = R.run(folder, b.map_jobs, b.score, out=tmp_path / "b", grid=TINY)
    assert a.blobs == b.blobs
    assert rep_a["winner"]["key"] == rep_b["winner"]["key"]
    assert rep_a["winner"]["objective"] == rep_b["winner"]["objective"]
    assert len(a.heldout_calls) == len(b.heldout_calls) == 1
    assert [s["id"] for s in a.heldout_calls[0]["sessions"]] == ["h-w4"]
    assert rep_a["heldout"]["chosen"]["score"] != rep_b["heldout"]["chosen"]["score"]


def test_sealed_sessions_open_once_and_only_for_a_choice():
    s = C.Sealed([{"id": "h", "hash": "x"}])
    with pytest.raises(C.Refused):
        s.open({})
    assert s.open({"window_ms": 1000})
    with pytest.raises(C.Refused):
        s.open({"window_ms": 1000})


def test_a_heldout_session_is_scored_once_across_runs(folder, tmp_path):
    spy = Spy()
    first = R.run(folder, spy.map_jobs, spy.score, out=tmp_path, grid=TINY)
    second = R.run(folder, spy.map_jobs, spy.score, out=tmp_path, grid=TINY)
    assert first["heldout"] and second["heldout"] is None
    assert len(spy.heldout_calls) == 1
    assert second["spent_heldout"] == ["h-w4"]
    assert any("heldout" in t for t in second["readiness"]["record_next"])


def test_refuses_a_winner_with_fewer_than_four_training_sessions(folder, tmp_path):
    (folder / "t-w3.jsonl").unlink()
    spy = Spy()
    rep = R.run(folder, spy.map_jobs, spy.score, out=tmp_path, grid=TINY)
    assert rep["refused"].startswith("No winner picked")
    assert spy.blobs == [] and spy.heldout_calls == []       # nothing went up
    text = (Path(rep["folder"]) / "summary.md").read_text()
    assert "Record next" in text and "more people" in text


def test_refuses_a_file_that_still_holds_identifiers(folder, tmp_path):
    _rewrite(folder / "t-w1.jsonl", lambda m: dict(m, peer_mac="aa:bb:cc:dd:ee:ff") if m["type"] == "label" else m)
    with pytest.raises(C.Refused, match="sim.scrub"):
        C.load_folder(folder)
    spy = Spy()
    rep = R.run(folder, spy.map_jobs, spy.score, out=tmp_path, grid=TINY)
    assert "identifiers" in rep["refused"] and spy.blobs == []


def test_real_recordings_need_the_scrubbed_flag(folder):
    for p in folder.glob("*.jsonl"):
        if p.name != "baselines.jsonl":
            _rewrite(p, lambda m: dict(m, src="live"))
    with pytest.raises(C.Refused, match="--scrubbed"):
        C.load_folder(folder)
    assert C.load_folder(folder, scrubbed=True)["label"] == "from recordings"


def test_simulated_and_real_sessions_never_mix(folder):
    _rewrite(folder / "t-w1.jsonl", lambda m: dict(m, src="live"))
    with pytest.raises(C.Refused, match="mixes"):
        C.load_folder(folder, scrubbed=True)


def test_tables_are_labelled_and_the_link_rows_match_the_device_table(folder, tmp_path):
    proof = [p for p in (C.REPO / "PROOF.md", C.REPO / "proof" / "proof.json") if p.exists()]
    before = [p.stat().st_mtime_ns for p in proof]
    spy = Spy()
    rep = R.run(folder, spy.map_jobs, spy.score, out=tmp_path, grid=TINY)
    assert [p.stat().st_mtime_ns for p in proof] == before      # never PROOF.md or proof.json
    out = Path(rep["folder"])
    assert sorted(p.name for p in out.iterdir()) == ["links.json", "links.md", "settings.json", "summary.md",
                                                    "top.md", "variants.jsonl"]
    for name in ("links.md", "top.md", "summary.md"):
        assert "(simulated)" in (out / name).read_text()
    assert json.loads((out / "settings.json").read_text())["data"] == "simulated"
    rows = json.loads((out / "links.json").read_text())["rows"]
    assert [r["name"] for r in rows] == ["all", "strip_crossing", "four_nodes", "router_receiver"]
    for r in rows:
        assert set(r) >= {"name", "nodes", "links", "zone"} and set(r["zone"]) >= {"correct", "total"}
    swept = {r["name"]: r for r in rows}
    assert swept["all"]["zone"]["total"] and swept["router_receiver"]["zone"]["total"]
    assert swept["router_receiver"]["links"] == ["pi5>unoq:wifi", "pi5>unoq:ble"]
    assert swept["strip_crossing"]["zone"]["total"] is None    # not in this grid: unknown, never invented


def test_a_second_desk_is_a_baseline_that_moved_a_link():
    h = [{"t": 1, "base": {"a": -50.0}}, {"t": 2, "base": {"a": -50.5}}, {"t": 3, "base": {"a": -55.0}}]
    assert C._desks(h) == [0, 0, 1]


def test_folds_leave_one_walker_out_and_keep_empty_sessions_in_training():
    s = [{"id": "a", "walker": "w1", "desk": 0}, {"id": "b", "walker": "w2", "desk": 0},
         {"id": "e", "walker": None, "desk": 0}]
    f = C.folds(s)
    assert f["walker"] == [(["b", "e"], ["a"]), (["a", "e"], ["b"])] and "desk" not in f


def test_both_feature_modes_come_from_the_window():
    w = {"links": {"x": {"n": 2, "mean": -60.0, "std": 1.0, "min": -61.0, "max": -59.0, "drop_db": 5.0}},
         "base": {"x": -55.0}}
    assert C.vector(w, ["x"], "absolute") == [-60.0, 1.0, -61.0, -59.0, 5.0]
    assert C.vector(w, ["x"], "relative") == [5.0, 1.0, 4.0, 6.0]
