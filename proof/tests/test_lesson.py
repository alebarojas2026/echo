import pytest

import json

from proof.lesson import Coach, label_summary

T0 = 1_763_149_500_000


def state(s, pred=None, teacher=None, lesson=None, cam="on"):
    block = lambda zone: None if zone is None else {"present": zone != 0, "zone": zone}   # noqa: E731
    training = None if lesson is None else {"lesson": dict(zip(("agree", "of", "fits"), lesson))}
    return {"type": "state", "t": T0 + round(s * 1000), "cam": cam, "pred": block(pred),
            "teacher": block(teacher), "model": {"training": training}}


def run(messages, **kw):
    sent, said = [], []
    coach = Coach("lesson-01", "w1", sent.append, said.append, **kw)
    coach.start()
    for m in messages:
        coach.on_message(m)
    return coach, sent, said


def test_sends_the_screen_commands_in_order_and_train_while_recording():
    coach, sent, said = run([state(s / 10, teacher=0 if s < 60 else 1) for s in range(0, 315)])
    assert [m["cmd"] for m in sent] == ["label_mode", "record_start", "train"]
    assert sent[0]["args"] == {"mode": "person"}
    assert sent[1]["args"] == {"session": "lesson-01", "purpose": "train", "walker": "w1"}
    assert all(m["v"] == 2 and m["type"] == "cmd" for m in sent)
    steps = [line.strip() for line in said if "Step " in line or "Stay out" in line]
    assert [w.split(":")[0].split(" and ")[0] for w in steps] == [
        "Stay out of the camera's view", "Step in on your LEFT", "Step to your RIGHT",
        "Step right out of the camera's view", "Step in on your LEFT", "Step to your RIGHT", "Step to your LEFT"]
    assert "empty time: 1 stretch of 3 s or more" in coach.summary()
    coach.stop()
    assert [m["cmd"] for m in sent[-2:]] == ["record_stop", "label_mode"] and sent[-1]["args"] == {"mode": "off"}


def test_times_the_first_model_the_first_right_answer_and_the_agreement():
    messages = [state(s, teacher=0 if s < 6 else 1) for s in range(0, 31)]
    messages.append({"type": "event", "kind": "trained", "t": T0 + 32_500})
    messages += [state(33, pred=2, teacher=1, lesson=(0, 1, 1)), state(34, pred=1, teacher=1, lesson=(1, 2, 1))]
    messages.append({"type": "event", "kind": "trained", "t": T0 + 37_000})      # a later fit is not the first
    messages += [state(s, pred=1, teacher=1, lesson=(8, 10, 2)) for s in range(35, 42)]
    messages += [state(43, pred=1, cam="off")]
    coach, sent, said = run(messages)
    assert coach.model_s == 32.5 and coach.follows_s == 34 and coach.report == (8, 10, 2)
    text = "\n".join(said)
    assert "learning: 8 of 10" in text and "the camera is off" in text
    assert "8 of the last 10 decisions (2 fits)" in coach.summary()


def test_a_lesson_with_no_empty_time_is_not_finished_until_the_camera_sees_nobody():
    """Someone in view the whole time, or standing back (teacher null: the label was dropped), is not empty."""
    busy = [state(s, teacher=1 if s % 2 else None) for s in range(0, 40)]
    coach, sent, said = run(busy)
    assert "train" not in [m["cmd"] for m in sent]
    assert sum("has no empty time yet" in line for line in said) == 1          # said once, plainly
    assert "empty time: none (the lesson was not finished: no train was sent)" in coach.summary()
    for s in (40, 41, 42):                                                     # 2 s of nobody is not enough
        coach.on_message(state(s, teacher=0))
    assert "train" not in [m["cmd"] for m in sent]
    coach.on_message(state(43, teacher=0))                                     # 3 s is: train goes at once
    assert [m["cmd"] for m in sent][-1] == "train"
    off, sent2, _ = run([state(s, teacher=0, cam="off") for s in range(0, 40)])
    assert "train" not in [m["cmd"] for m in sent2]                            # the camera off is not "nobody"


def test_a_model_trained_before_the_lesson_is_not_counted_as_its_first():
    coach, _, _ = run([state(0, pred=0), {"type": "event", "kind": "trained", "t": T0 + 1000}, state(2, pred=0)])
    assert coach.model_s is None and "first model: never" in coach.summary()
    assert "not reached" in coach.summary()


def test_no_lesson_block_is_said_plainly():
    coach, _, _ = run([state(0), state(41)], teach_s=5)
    assert coach.report == () and "no lesson was running" in coach.summary()


@pytest.mark.parametrize("session, walker", [("bad id", "w1"), ("ok", " ")])
def test_bad_ids_are_refused(session, walker):
    with pytest.raises(ValueError):
        Coach(session, walker, lambda m: None)


def test_recording_without_a_lesson_never_sends_train():
    coach, sent, said = run([state(s, teacher=1) for s in range(0, 40)], purpose="demo", train=False)
    coach.stop()
    assert [m["cmd"] for m in sent] == ["label_mode", "record_start", "record_stop", "label_mode"]
    assert sent[1]["args"]["purpose"] == "demo" and not any("Step to your" in line for line in said)
    assert "no lesson was asked for" in said[-1]


def test_label_summary_counts_what_the_camera_said():
    def label(i, persons=1, zone=1, clipped=False):
        return json.dumps({"type": "label", "t": i * 100, "recv_t": i * 100, "persons_in_frame": persons,
                           "zone": None if clipped else zone, "clipped": clipped})
    lines = [label(0, 0, 0), label(1), label(2), label(3, zone=2), label(4, clipped=True),
             label(5, 2, clipped=True), '{"type":"rssi"}', '{"type":"lab']
    text = label_summary(lines)
    assert "6 labels in 0.5 s (10.0 a second)" in text and "nobody in frame: 1" in text
    assert "one person, usable: 3   zone 1: 2   zone 2: 1" in text
    assert "dropped (dead band or side edge): 1" in text and "more than one person: 1" in text
    assert label_summary(['{"type":"rssi"}']) == "no camera labels in this recording"
