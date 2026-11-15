"""Operator key (#657, wording in #654): with a key on the board, only a cmd that carries it is acted on."""
import logging

from brain.core import Brain

KEY = "desk-7-key"


def cmd(name, key=None, **args):
    msg = {"v": 2, "type": "cmd", "cmd": name, "args": args}
    if key is not None:
        msg["key"] = key
    return msg


def locked(**kw):
    sent = []
    return Brain(operator_key=KEY, to_bus=sent.append, **kw), sent


def test_commands_without_the_key_change_nothing(caplog):
    brain, sent = locked()
    with caplog.at_level(logging.WARNING, logger="brain"):
        for name, args in (("arm", {"on": True}), ("reset", {}), ("baseline", {}), ("relearn", {}), ("train", {}),
                           ("record_start", {"session": "s1", "purpose": "train", "walker": "w1"}),
                           ("label_mode", {"mode": "person"}), ("router_moved", {"spot": "S-W30"})):
            brain.on_cmd(cmd(name, **args))
    assert not brain.armed.on and brain.capture is None and brain.want_session is None
    assert brain.label_mode == "off" and brain.router == "S-home"
    assert brain.events == [] and sent == [] and brain.refused == 8      # no event, nothing sent to the bus
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "ignored" in text and KEY not in text                         # one line each, never the key


def test_a_wrong_key_or_an_odd_one_is_refused_too():
    brain, _ = locked()
    for bad in ("desk-7-keY", "", KEY + "x", KEY[:-1], 12345, None, ["desk-7-key"], {"k": KEY}):
        msg = cmd("arm", on=True)
        msg["key"] = bad
        brain.on_cmd(msg)
    assert not brain.armed.on and brain.refused == 8


def test_with_the_key_they_work_and_the_key_goes_nowhere():
    brain, sent = locked()
    brain.on_cmd(cmd("arm", key=KEY, on=True))
    brain.on_cmd(cmd("baseline", key=KEY))
    brain.on_cmd(cmd("label_mode", key=KEY, mode="person"))
    assert brain.armed.on and brain.capture is not None and brain.label_mode == "person"
    assert [m["cmd"] for m in sent][:2] == ["arm", "baseline"]
    assert all("key" not in m and KEY not in str(m) for m in sent)       # not forwarded, so never recorded
    assert all(KEY not in str(e) for e in brain.events)
    assert KEY not in str(brain.state())


def test_truth_needs_no_key():
    brain, sent = locked()
    brain.on_cmd(cmd("truth", zone=2))                                   # the crowd game's phones
    assert brain.truth == 2 and [m["cmd"] for m in sent] == ["truth"] and brain.refused == 0


def test_state_says_locked_only_when_a_key_is_set():
    assert locked()[0].state()["locked"] is True
    assert "locked" not in Brain().state()                               # missing means false


def test_without_a_key_everything_is_as_before():
    for key in (None, ""):
        brain = Brain(operator_key=key)
        brain.on_cmd(cmd("arm", on=True))
        brain.on_cmd(cmd("arm", key="anything", on=False))               # a key nobody asked for is ignored
        assert not brain.armed.on and brain.refused == 0


def test_the_brains_own_steps_are_not_locked_out(tmp_path):
    brain = Brain(operator_key=KEY, sessions_dir=tmp_path)
    brain.on_cmd(cmd("arm", key=KEY, on=True))
    again = Brain(operator_key=KEY, sessions_dir=tmp_path)               # the restart re-arms by itself
    assert again.armed.on


def test_main_reads_the_key_from_the_environment_only(monkeypatch):
    import inspect
    from brain import main
    src = inspect.getsource(main.main)
    assert 'os.environ.get("OPERATOR_KEY")' in src
    assert "--operator-key" not in src and "--key" not in src           # never a flag: flags show in the process list
