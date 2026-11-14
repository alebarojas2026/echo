import json
import pytest
from teacher.applab.python.labels import Projection, Teacher, attach_processed_results


def projection():
    return Projection({"homography": [[0.01, 0, -1], [0, -0.01, 3], [0, 0, 1]], "image_size": [400, 400]})


def box(x=140, y=100, w=20, h=100):
    return dict(label="person", value=0.9, x=x, y=y, width=w, height=h)


def test_processed_empty_and_non_person():
    sent = []
    teacher = Teacher(projection(), sent.append, clock=lambda: 1000)
    a = teacher.processed([])
    b = teacher.processed([dict(label="chair", value=0.99)])
    assert a["present"] is False and a["zone"] == 0 and a["motion"] is None
    assert b["persons_in_frame"] == 0 and b["frame"] == 2
    assert a["v"] == 2 and a["seq"] == 1 and a["src"] == "live"


def test_foot_zone_outside_and_clipped():
    teacher = Teacher(projection(), lambda _: None)
    assert teacher.processed([box()])["zone"] == 1
    outside = teacher.processed([box(x=330)])
    assert outside["persons_in_frame"] == 1 and not outside["present"]
    clipped = teacher.processed([box(y=0)])
    assert clipped["clipped"] and clipped["zone"] is None and clipped["foot_m"] is None
    assert teacher.processed([box(), box(x=240)])["clipped"]


def test_motion_filter_and_gap():
    t = [0]
    teacher = Teacher(projection(), lambda _: None, clock=lambda: t[0])
    labels = []
    for i in range(21):
        t[0] = i * 100
        labels.append(teacher.processed([box(x=140 + i * 4)]))
    assert labels[-1]["motion"] == "moving"
    t[0] += 1000
    assert teacher.processed([box()])["motion"] == "still"
    for i in range(21):
        t[0] += 100
        label = teacher.processed([box(x=140 + (80 if i == 10 else 0))])
    assert label["motion"] == "still"


def test_result_hook_ignores_silence_control_and_missing_boxes():
    class FakeBrick:
        def __init__(self):
            self.original_calls = 0
        def _process_message(self, ws, message):
            self.original_calls += 1

    brick, sent = FakeBrick(), []
    mode = ["off"]
    teacher = Teacher(projection(), sent.append, mode=lambda: mode[0])
    attach_processed_results(brick, teacher)
    for msg in [{"type": "hello"}, {"type": "classification", "result": {}},
                {"type": "classification", "result": {"bounding_boxes": []}}]:
        brick._process_message(None, json.dumps(msg))
    assert len(sent) == 1 and sent[0]["mode"] == "off"
    mode[0] = "object"
    brick._process_message(None, json.dumps({"type": "classification", "result": {"bounding_boxes": [box()]}}))
    assert sent[-1]["mode"] == "object" and sent[-1]["persons_in_frame"] == 1
    assert brick.original_calls == 4


@pytest.mark.parametrize("failure", ["mode", "send"])
def test_adapter_failure_preserves_brick_processing(failure, caplog):
    class FakeBrick:
        original_calls = 0
        def _process_message(self, ws, message):
            self.original_calls += 1

    sent = []
    def mode():
        if failure == "mode":
            raise FileNotFoundError("mode unavailable")
        return "person"

    def send(label):
        if failure == "send":
            raise OSError("bus unavailable")
        sent.append(label)

    brick = FakeBrick()
    attach_processed_results(brick, Teacher(projection(), send, mode=mode))
    message = json.dumps({"type": "classification", "result": {"bounding_boxes": []}})
    brick._process_message(None, message)
    brick._process_message(None, message)
    assert not sent and brick.original_calls == 2
    assert len(caplog.records) == 1
