"""A command that can't be carried out in full must not take the rest down with it."""
import logging

from brain.core import Brain
from brain.tests.test_core import cmd


def test_a_mode_file_that_cannot_be_written_does_not_stop_the_baseline(tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger="brain")
    brain = Brain(mode_file=tmp_path / "no-such-folder" / "label_mode")
    brain.on_cmd(cmd("baseline"))                 # sets label mode off first, then starts the capture
    assert brain.capture is not None and brain.label_mode == "off"
    brain.on_cmd(cmd("label_mode", mode="object"))
    assert brain.label_mode == "object"
    assert sum("could not write label mode" in r.getMessage() for r in caplog.records) == 2


def test_args_that_are_not_an_object_are_dropped():
    sent = []
    brain = Brain(to_bus=sent.append)
    for args in (["s1"], "s1", 7):
        brain.on_cmd({"v": 2, "type": "cmd", "cmd": "record_start", "args": args})
    brain.on_cmd({"v": 2, "type": "cmd", "cmd": ["reset"], "args": {}})
    assert sent == [] and brain.events == [] and brain.want_session is None
