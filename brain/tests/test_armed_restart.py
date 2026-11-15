"""Armed mode survives a brain restart (#647, #693); a second baseline tap is ignored (#649)."""
import json
import logging

from brain.core import Brain
from brain.tests.simdata import T0_MS


def run(seconds, in_view, present=lambda s: False, dbm=lambda s, link: -55, brain=None):
    """10 Hz of cam, label and one reading per link. in_view(s) = somebody is in the camera's frame.
    Returns (brain, seconds at which baseline_done came, or None)."""
    b = brain or Brain()
    if brain is None:
        b.on_cmd({"v": 2, "type": "cmd", "cmd": "baseline", "args": {}})
    done, seq = None, 0
    for i in range(int(seconds * 10)):
        s, t = i / 10, T0_MS + i * 100
        seen = bool(in_view(s))
        msgs = [{"type": "cam", "state": "on", "fps": 9},
                {"type": "label", "frame": i, "mode": "off", "persons_in_frame": int(seen),
                 "present": seen and bool(present(s)), "zone": 0, "foot_m": None, "motion": None,
                 "conf": 0.9, "clipped": False}]
        msgs += [{"type": "rssi", "link": link, "kind": link.split(":")[1], "tx": link.split(">")[0],
                  "rx": link.split(">")[1].split(":")[0], "dbm": dbm(s, link)} for link in b.links]
        for m in msgs:
            seq += 1
            b.on_message({"v": 2, "t": t, "seq": seq, "src": "sim", "recv_t": t, **m})
        b.state()
        if done is None and any(e["kind"] == "baseline_done" for e in b.pop_events()):
            done = s
    return b, done


def cmd(name, **args):
    return {"v": 2, "type": "cmd", "cmd": name, "args": args}


def kinds(brain):
    return [e["kind"] for e in brain.events]


def test_a_restart_while_armed_comes_back_armed_and_says_so(tmp_path):
    brain = Brain(sessions_dir=tmp_path)
    brain.on_cmd(cmd("arm", on=True))
    assert json.loads((tmp_path / "armed.json").read_text())["on"] is True
    assert not (tmp_path / "armed.json.tmp").exists()

    again = Brain(sessions_dir=tmp_path)               # a crash, a redeploy or a power blip
    assert again.armed.on and again.state()["armed"] is True
    assert kinds(again) == ["armed"]                   # the restart shows as a second armed event


def test_disarmed_stays_disarmed_after_a_restart(tmp_path):
    brain = Brain(sessions_dir=tmp_path)
    brain.on_cmd(cmd("arm", on=True))
    brain.on_cmd(cmd("arm", on=False))
    again = Brain(sessions_dir=tmp_path)
    assert not again.armed.on and kinds(again) == []


def test_reset_disarms_on_disk_too(tmp_path):
    brain = Brain(sessions_dir=tmp_path)
    brain.on_cmd(cmd("arm", on=True))
    brain.on_cmd(cmd("reset"))
    assert json.loads((tmp_path / "armed.json").read_text())["on"] is False
    assert not Brain(sessions_dir=tmp_path).armed.on


def test_a_missing_cut_off_or_odd_file_reads_as_not_armed(tmp_path):
    assert not Brain(sessions_dir=tmp_path).armed.on            # no file
    for text in ('{"on": tr', "", "[]", '{"on": "yes"}', '{"t": 5}'):
        (tmp_path / "armed.json").write_text(text)
        again = Brain(sessions_dir=tmp_path)
        assert not again.armed.on and kinds(again) == [], text


def test_a_failed_write_is_logged_and_does_not_stop_the_arm(tmp_path, caplog):
    blocked = tmp_path / "not-a-folder"
    blocked.write_text("a file where the folder should be")
    brain = Brain(sessions_dir=blocked)
    with caplog.at_level(logging.WARNING, logger="brain"):
        brain.on_cmd(cmd("arm", on=True))
    assert brain.armed.on and kinds(brain) == ["armed"]
    assert any("armed.json" in r.getMessage() for r in caplog.records)


def test_a_second_baseline_tap_does_not_start_the_capture_over():
    brain = Brain()
    brain.on_cmd(cmd("baseline"))
    tapped = []

    def in_view(s):
        if s >= 5 and not tapped:
            tapped.append(s)
            brain.on_cmd(cmd("baseline"))              # a double tap, 5 s in
        return False

    _, done = run(40, in_view, brain=brain)
    assert 20 <= done <= 20.5                          # 20 s after the first tap, not the second
    assert brain.capture is None


def test_a_changed_mind_still_replaces_the_capture():
    brain = Brain()
    brain.on_cmd(cmd("baseline", keep_model=True))
    switched = []

    def in_view(s):
        if s >= 5 and not switched:
            switched.append(s)
            brain.on_cmd(cmd("baseline"))              # keep the model, then: no, a new place
        return False

    _, done = run(40, in_view, brain=brain)
    assert 25 <= done <= 25.6 and brain.place_t is not None
