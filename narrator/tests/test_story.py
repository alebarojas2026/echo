"""The story templates and the rule for the model's wording (narrator/story.py), on hand-made records."""
import time

import pytest

from narrator import story as s

T0 = 1_763_200_020_000
SPOT = {1: "At the desk"}
DESK = {1: "Left", 2: "Right"}
DEVICES = {"unoq": "Board", "pi5": "Pi A", "pi5b": "Pi B"}


def ev(sec, kind, seq, **info):
    return {"t": T0 + sec * 1000, "kind": kind, "id": f"{kind}{sec}", "info": info, "seq": seq}


def second(sec, seq, present=0, motion=None, armed=False):
    return {"t": T0 + sec * 1000, "present": present, "kind": "person" if present else "none", "zone": 1 if present else 0,
            "motion": motion, "armed": int(armed), "seq": seq}


def test_the_clock_is_said_as_a_person_says_it():
    t = time.mktime((2026, 11, 15, 2, 14, 30, 0, 0, -1)) * 1000
    assert s.hm(t) == "2:14 AM" and s.hm(t + 11 * 3_600_000) == "1:14 PM" and s.hm(t - 2 * 3_600_000) == "12:14 AM"


def test_two_walk_throughs_in_one_minute_are_said_once_with_twice():
    events = [ev(1, "enter", 1, zone=1), ev(2, "exit", 2, zone=1), ev(3, "passed_by", 3, zone=1),
              ev(5, "enter", 4, zone=1), ev(6, "exit", 5, zone=1), ev(7, "passed_by", 6, zone=1)]
    items = s.timeline(events, [], SPOT, DEVICES, T0, T0 + 59_000)
    assert [i["text"] for i in items] == ["Somebody walked through at the desk twice."]
    assert items[0]["cites"] == [1, 2, 3, 4, 5, 6]


def test_a_visit_says_its_still_stretch_and_how_long_until_they_left():
    seconds = [second(i, 10 + i, present=1, motion="moving" if i < 2 else "still") for i in range(0, 42)]
    events = [ev(0, "enter", 1, zone=1), ev(42, "exit", 2, zone=1)]
    items = s.timeline(events, seconds, SPOT, DEVICES, T0, T0 + 60_000)
    assert [i["text"] for i in items] == ["Somebody stepped in at the desk and stood still for 40 seconds.",
                                          "They left after 42 seconds."]
    assert items[0]["cites"] == [1] + list(range(12, 52)) and items[1]["cites"] == [2]


def test_on_the_desk_strip_the_side_is_said_and_somebody_already_there_is_not_said_to_arrive():
    seconds = [second(i, i + 1, present=1, motion="moving") for i in range(5)]
    items = s.timeline([ev(5, "exit", 9, zone=1)], seconds, DESK, DEVICES, T0, T0 + 10_000)
    assert [i["text"] for i in items] == ["Somebody was already here on the left and moved for 5 seconds.", "They left."]


def test_a_device_that_went_quiet_while_armed_and_never_came_back():
    seconds = [second(0, 1, armed=True)]
    items = s.timeline([ev(3, "tamper", 2, node="pi5b")], seconds, SPOT, DEVICES, T0, T0 + 30_000)
    assert items[0]["text"] == ("Pi B went quiet while the space was armed and had not come back by the end of "
                                "this stretch.")


def test_the_story_says_each_minute_once():
    items = [{"t": T0, "text": "A.", "cites": []}, {"t": T0 + 1000, "text": "B.", "cites": []},
             {"t": T0 + 120_000, "text": "C.", "cites": []}]
    told = s.tell(items)
    assert told == f"{s.hm(T0)}. A. B. {s.hm(T0 + 120_000)}. C."


def test_nothing_in_a_stretch_is_said_plainly():
    assert s.nothing([], T0, T0 + 60_000) == f"I have no records between {s.hm(T0)} and {s.hm(T0 + 60_000)}."
    quiet = [second(0, 1), {**second(1, 2), "present": None}]
    assert s.nothing(quiet, T0, T0 + 60_000).endswith("Nobody was seen. For 1 second of it the sensor could not tell.")


STORY = "2:14 AM. Somebody stepped in at the desk and stood still for 40 seconds. 2:16 AM. Pi B went quiet for 8 seconds."


@pytest.mark.parametrize("written, why", [
    ("2:14 AM. Someone stepped in at the desk and stayed still for 40 seconds. 2:16 AM. Pi B went quiet for 8 seconds.", None),
    ("2:14 AM. Somebody stood still for 41 seconds. 2:16 AM. Pi B went quiet for 8 seconds.", "a time or a number"),
    ("2:15 AM. Somebody stood still for 40 seconds. 2:16 AM. Pi B went quiet for 8 seconds.", "a time or a number"),
    ("2:14 AM. Somebody stood still for 40 seconds.", "a time or a number"),
    ("2:14 AM. Somebody stood still for 40 seconds. 2:16 AM. Pi B went quiet for 8 seconds, 3 times.", "a time or a number"),
    ("2:14 AM. A woman stood still for 40 seconds. 2:16 AM. Pi B went quiet for 8 seconds.", "a word we never use"),
    ("", "empty")])
def test_the_model_may_change_the_words_but_never_a_time_or_a_number(written, why):
    found = s.problem(written, STORY)
    assert (found is None) if why is None else found.startswith(why)


def test_smoothing_falls_back_to_the_template_when_the_model_fails():
    def down(_):
        raise ConnectionError("refused")
    assert s.smooth(STORY, down) == (STORY, "template (refused)")
    assert s.smooth(STORY, None) == (STORY, "template")
    assert s.smooth(STORY, lambda m: STORY.replace("Somebody", "Someone"))[1] == "llm"
