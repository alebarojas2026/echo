"""On a layout with a presence line the proof tools score the brain's own decisions with no model.
Layouts without one keep every check they had."""
import json

import pytest

from proof import layout as L, line_stats, run_all
from proof.presence import score_cycles
from proof.presence_walk import fresh_ready, run
from proof.tests.conftest import FIXTURES
from proof.tests.test_score import session
from proof.tests.test_trials import LAYOUT, annotation, recording
from proof.trials import analyze

GATE_FILE = FIXTURES.parents[2] / "radio" / "layouts" / "gate.json"   # the layout file the kit runs: it names the presence line
GATE = L.load(GATE_FILE)
DESK = L.load(FIXTURES / "desk-nodes.json")
LOG = [(0, False), (60000, True), (120000, False)]


def cold_states(**change):
    """What a brain with no model, no lesson and no camera says once a second."""
    return [dict(dict(v=2, type="state", recv_t=t, src="live", cam="unknown", health={"status": "ok"},
                      model={"trained": False}, pred={"present": 60000 <= t < 120000}), **change)
            for t in range(0, 120001, 1000)]


def test_the_layout_says_whether_a_line_decides():
    assert L.presence_line(GATE) == "pi5>pi5b:wifi" and L.presence_line(DESK) is None


def test_cycles_are_scored_with_no_model_and_no_training_files_on_a_presence_line():
    r = score_cycles(session("cycles"), cold_states(), LOG, [], layout=GATE)
    assert (r["correct"], r["total"], r["always_empty_correct"], r["cycles"]) == (120, 120, 60, 1)
    assert "pi5>pi5b:wifi decides, no model" in r["method"]
    states = cold_states()
    states[70]["pred"]["present"] = False
    assert score_cycles(session("cycles"), states, LOG, [], layout=GATE)["correct"] == 119


def test_without_a_presence_line_a_model_and_its_training_files_are_still_required():
    with pytest.raises(ValueError, match="training provenance"):
        score_cycles(session("cycles"), cold_states(), LOG, [], layout=DESK)
    train = session("train", "train", 1)
    train["meta"]["walker"] = "training-walker"
    with pytest.raises(ValueError):
        score_cycles(session("cycles"), cold_states(cam="off"), LOG, [train], layout=DESK)


def test_a_camera_running_or_a_model_appearing_mid_run_is_refused_on_a_presence_line():
    for cam in ("on", "stalled"):
        states = cold_states()
        states[30]["cam"] = cam
        with pytest.raises(ValueError, match="camera"):
            score_cycles(session("cycles"), states, LOG, [], layout=GATE)
    states = cold_states()
    for s in states[60:]:
        s.update(cam="off", model={"trained": True, "ver": "m1", "train_sessions": []})
    with pytest.raises(ValueError):
        score_cycles(session("cycles"), states, LOG, [], layout=GATE)


def test_the_guide_waits_for_a_fresh_state_only_and_asks_for_no_camera_or_lesson():
    cold = {"cam": "unknown", "model": {"trained": False}, "recv_t": 5000}
    assert fresh_ready(cold, "pi5>pi5b:wifi", 5500) and not fresh_ready(cold, None, 5500)
    assert not fresh_ready(cold, "pi5>pi5b:wifi", 7000) and not fresh_ready(dict(cold, cam="on"), "pi5>pi5b:wifi", 5500)
    assert fresh_ready({"cam": "off", "model": {"trained": True}, "recv_t": 5000}, None, 5500)
    said, clock, marks = [], [0], []
    def sleep(s): clock[0] += s
    run("cycles", "w2", lambda m: None, lambda t, p: marks.append((t, p)), ask=said.append, say=said.append,
        sleep=sleep, clock=lambda: clock[0], line="pi5>pi5b:wifi")
    assert len(marks) == 21 and "No camera and no lesson are needed" in said[0]
    assert not any("camera still unplugged" in text or "lesson/training" in text for text in said)


def test_confirmed_positions_are_scored_with_no_model_on_a_presence_line():
    s, c, a = recording("heldout")
    for state in c:
        state.update(cam="unknown", model={"trained": False})
    a.append(annotation("walk", 1000, 3000, zone=7))
    assert analyze([(s, c, a)], LAYOUT)["lesson"]["unplugged_walk"]["total"] is None       # no line: a model is needed
    line = dict(LAYOUT, presence={"line": "pi5>pi5b:wifi"})
    walk = analyze([(s, c, a)], line)["lesson"]["unplugged_walk"]
    assert walk["correct"] == walk["total"] == 10
    c[20]["cam"] = "on"
    assert analyze([(s, c, a)], line)["lesson"]["unplugged_walk"]["total"] is None
    s2, c2, _ = recording("train")
    assert analyze([(s2, c2, [])], line)["lesson"]["sessions"] == []       # no lesson exists to time
    assert len(analyze([(s2, c2, [])], LAYOUT)["lesson"]["sessions"]) == 1


def test_a_line_group_may_state_its_placement_in_words_when_the_layout_file_was_not_kept():
    def member(name, start, layout_sha256=None, layout_note="one desk, the far device across a one metre gap"):
        return {"session": name, "group": "kit", "commit": "a" * 40, "layout_sha256": layout_sha256, "layout_note": layout_note,
                "started_at_ms": start, "ended_at_ms": start + 1000, "duration_s": 1, "source": "live", "method": line_stats.METHOD,
                "measured_at": "2026-01-01T00:00:00+00:00", "recording_sha256": "c" * 64, "annotations_sha256": "d" * 64,
                "lines": [{"link": "a>b:wifi", "readings": 4, "_windows": {k: [-40.0] for k in line_stats.KINDS},
                           "_jitter": {k: [0.0] for k in line_stats.KINDS}}]}
    report = line_stats.group_reports([member("one", 0), member("two", 2000)])[0]
    assert "the board's layout file was not kept; the operator's note: one desk" in "\n".join(line_stats.table([report]))
    for bad in (member("two", 2000, layout_note="another placement, the device on the floor"), member("two", 2000, layout_note=None),
                member("two", 2000, layout_sha256="b" * 64)):
        with pytest.raises(ValueError):
            line_stats.group_reports([member("one", 0), bad])
    with pytest.raises(ValueError):
        line_stats.group_reports([member("one", 0, layout_note="short"), member("two", 2000, layout_note="short")])


def test_the_pipeline_scores_cycles_with_no_training_recording_on_a_presence_line(tmp_path, monkeypatch):
    meta = dict(v=2, type="meta", recv_t=1000, src="live", session="cycles", purpose="heldout", walker="w2")
    (tmp_path / "cycles.jsonl").write_text(json.dumps(meta) + "\n")
    (tmp_path / "cycles.states.jsonl").write_text("{}\n")
    (tmp_path / "cycles.presence.csv").write_text("recv_t,present\n")
    for path, expected in ((GATE_FILE, True), (FIXTURES / "desk-nodes.json", False)):
        monkeypatch.setenv("RADIO_SIGHT_NODES", str(path))
        commands, _ = run_all.plan(tmp_path, tmp_path / "proof.json", tmp_path / "baseline.json", tmp_path / "PROOF.md")
        cycles = [c for c in commands if "proof.presence" in c]
        assert bool(cycles) == expected
        assert not cycles or "--train" not in cycles[0]
