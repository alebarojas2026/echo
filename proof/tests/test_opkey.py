"""Every proof tool that sends commands adds the operator key when OPERATOR_KEY is set (#657)."""
import pytest

from proof import lesson, opkey, security_walk, trials_walk, walk, presence_walk, shuffled

KEY = "desk-7-key"
LAYOUT = {"armed": {"hold_s": 3}, "zones": [{"id": 1, "name": "Spot", "still_alert_s": 10}]}


def lesson_cmds():
    sent = []
    coach = lesson.Coach("s-k1", "w1", sent.append, say=lambda text: None)
    coach.start()
    return sent


def security_cmds():
    sent = []
    security_walk.run("s-k2", "w1", "empty", LAYOUT, sent.append, prompt=lambda text: None,
                      sleep=lambda s: None, clock=lambda: 0.0, repeats=1)
    return sent


def trials_cmds():
    sent = []
    trials_walk.run("s-k3", "walk", "w1", LAYOUT, sent.append, lambda mark: None, ask=lambda text="": "",
                    say=lambda text: None, sleep=lambda s: None, clock=lambda: 0.0)
    return sent


def walk_cmds():
    import os
    sent, now = [], [0.0]
    walk.coach("s-k4", "train", "w1", sent.append, prompt=lambda text: None,
               sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0],
               key=os.environ.get("OPERATOR_KEY") or None)
    return sent


def presence_cmds():
    sent = []
    presence_walk.run("s-k5", "w1", sent.append, lambda *args: None, ask=lambda text="": "",
                      say=lambda text: None, sleep=lambda s: None, clock=lambda: 0.0)
    return sent


SENDERS = [lesson_cmds, security_cmds, trials_cmds, walk_cmds, presence_cmds]


@pytest.mark.parametrize("sender", SENDERS, ids=lambda f: f.__name__)
def test_every_cmd_carries_the_key_when_the_board_has_one(sender, monkeypatch):
    monkeypatch.setenv("OPERATOR_KEY", KEY)
    cmds = [m for m in sender() if m.get("type") == "cmd"]
    assert cmds and all(m.get("key") == KEY for m in cmds)


@pytest.mark.parametrize("sender", SENDERS, ids=lambda f: f.__name__)
def test_without_a_key_the_cmds_are_as_before(sender, monkeypatch):
    monkeypatch.delenv("OPERATOR_KEY", raising=False)
    cmds = [m for m in sender() if m.get("type") == "cmd"]
    assert cmds and all("key" not in m for m in cmds)


def test_an_empty_key_is_no_key(monkeypatch):
    monkeypatch.setenv("OPERATOR_KEY", "")
    msg = {"v": 2, "type": "cmd", "cmd": "arm", "args": {}}
    assert opkey.with_key(msg) is msg


@pytest.mark.parametrize('key',[None,KEY])
def test_shuffled_recording_keys_both_commands_but_never_saves_the_key(key,monkeypatch,tmp_path,capsys):
    import json
    from types import SimpleNamespace
    import websockets.sync.client
    sent = []
    class Socket:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def __iter__(self): return iter(())
        def recv(self): return json.dumps({'type':'state','src':'live'})
        def send(self,text): sent.append(json.loads(text))
    if key: monkeypatch.setenv('OPERATOR_KEY',key)
    else: monkeypatch.delenv('OPERATOR_KEY',raising=False)
    monkeypatch.setattr(websockets.sync.client,'connect',lambda url: Socket())
    monkeypatch.setattr(shuffled.subprocess,'run',lambda *a,**k: SimpleNamespace(stdout='a'*40))
    shuffled.record(SimpleNamespace(session='empty-key-check',sessions=tmp_path,url='unused',tuning=False,minutes=0),'empty')
    assert [m['args']['on'] for m in sent] == [True,False]
    assert all(m.get('key') == key for m in sent)
    if key is None: assert all('key' not in m for m in sent)
    assert KEY not in capsys.readouterr().out
    assert KEY not in (tmp_path/'empty-key-check.shuffled.jsonl').read_text()
