import pytest

from proof.lesson import Coach

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
    coach, sent, said = run([state(s / 10, teacher=1) for s in range(0, 215)])
    assert [m["cmd"] for m in sent] == ["label_mode", "record_start", "train"]
    assert sent[0]["args"] == {"mode": "person"}
    assert sent[1]["args"] == {"session": "lesson-01", "purpose": "train", "walker": "w1"}
    assert all(m["v"] == 2 and m["type"] == "cmd" for m in sent)
    steps = [line for line in said if "Step to your" in line]
    assert len(steps) == 5 and "LEFT" in steps[0] and "RIGHT" in steps[1]
    coach.stop()
    assert [m["cmd"] for m in sent[-2:]] == ["record_stop", "label_mode"] and sent[-1]["args"] == {"mode": "off"}


def test_times_the_first_model_the_first_right_answer_and_the_agreement():
    messages = [state(s, teacher=1) for s in range(0, 21)]
    messages.append({"type": "event", "kind": "trained", "t": T0 + 22_500})
    messages += [state(23, pred=2, teacher=1, lesson=(0, 1, 1)), state(24, pred=1, teacher=1, lesson=(1, 2, 1))]
    messages.append({"type": "event", "kind": "trained", "t": T0 + 27_000})      # a later fit is not the first
    messages += [state(s, pred=1, teacher=1, lesson=(8, 10, 2)) for s in range(25, 32)]
    messages += [state(33, pred=1, cam="off")]
    coach, sent, said = run(messages)
    assert coach.model_s == 22.5 and coach.follows_s == 24 and coach.report == (8, 10, 2)
    text = "\n".join(said)
    assert "learning: 8 of 10" in text and "the camera is off" in text
    assert "8 of the last 10 decisions (2 fits)" in coach.summary()


def test_a_model_trained_before_the_lesson_is_not_counted_as_its_first():
    coach, _, _ = run([state(0, pred=0), {"type": "event", "kind": "trained", "t": T0 + 1000}, state(2, pred=0)])
    assert coach.model_s is None and "first model: never" in coach.summary()
    assert "not reached" in coach.summary()


def test_no_lesson_block_is_said_plainly():
    coach, _, _ = run([state(0), state(31)], teach_s=5)
    assert coach.report == () and "no lesson was running" in coach.summary()


@pytest.mark.parametrize("session, walker", [("bad id", "w1"), ("ok", " ")])
def test_bad_ids_are_refused(session, walker):
    with pytest.raises(ValueError):
        Coach(session, walker, lambda m: None)
