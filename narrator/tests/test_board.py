"""How the narrator behaves on the board: the model server starting late or answering slowly,
the cache slot the recap shares, and a reset between judges."""
import threading
import time

from narrator import narrate as n
from narrator import recap as r

NOW = 1_763_149_512_000


def ev(kind, t=NOW, id="e1", **info):
    return {"v": 2, "type": "event", "t": t, "seq": 1, "src": "live", "id": id, "kind": kind, "info": info}


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_warm_up_retries_until_the_model_server_has_loaded():
    replies = [ConnectionRefusedError("not up yet"), OSError("HTTP Error 503: Loading model"), ("Hi.", "m")]
    calls = []

    def llm(msgs):
        calls.append(msgs)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    clock = FakeClock()
    assert n.Warmer(llm, retry_s=2, sleep=clock.sleep, clock=clock).run() is True
    assert len(calls) == 3 and clock.t == 4
    assert calls[0] == n.prompt("enter", n.template("enter", {"zone": 2}))   # the sentence prompt


def test_warm_up_gives_up_after_a_while():
    clock = FakeClock()

    def down(msgs):
        raise ConnectionRefusedError("down")

    assert n.Warmer(down, retry_s=2, give_up_s=10, sleep=clock.sleep, clock=clock).run() is False
    assert clock.t <= 10


def test_one_warm_up_at_a_time():
    release = threading.Event()
    calls = []

    def llm(msgs):
        calls.append(1)
        release.wait(5)
        return "Hi.", "m"

    warmer = n.Warmer(llm)
    assert warmer.kick() is True
    assert warmer.kick() is False        # still running
    release.set()
    for _ in range(100):
        if warmer._busy.acquire(blocking=False):
            warmer._busy.release()
            break
        time.sleep(0.01)
    assert calls == [1]
    assert warmer.kick() is True         # done, so a new one may start
    release.set()


def test_a_failed_sentence_call_kicks_a_warm_up():
    kicks = []

    def down(msgs):
        raise ConnectionRefusedError("down")

    nar = n.Narrator(down, lambda m: None, clock=lambda: NOW)
    nar.warm = lambda: kicks.append(1)
    nar.observe(ev("enter", zone=2))
    msg = nar.step()
    assert msg["source"] == "template" and kicks == [1]


def test_a_call_that_never_got_a_worker_is_never_sent():
    hold = threading.Event()
    blockers = [n.POOL.submit(hold.wait, 5) for _ in range(n.POOL._max_workers)]
    sent = []
    try:
        try:
            n.within(0.05, sent.append, "late")
        except TimeoutError:
            pass
        else:
            raise AssertionError("expected a timeout")
    finally:
        hold.set()
        for b in blockers:
            b.result()
    time.sleep(0.05)
    assert sent == []


def test_reset_drops_the_waiting_event_so_the_recap_is_next():
    nar = n.Narrator(lambda m: ("Someone just stepped into zone 2.", "m"), lambda m: None, clock=lambda: NOW)
    nar.observe(ev("alert_off", zone=4))
    assert nar.pending
    nar.observe(ev("reset", id="e9"))
    assert nar.pending is None and nar.step() is None


def test_the_recap_puts_the_sentence_prompt_back_in_the_cache():
    kicks, sent = [], []
    nar = n.Narrator(lambda m: ("", None), sent.append, clock=lambda: NOW)
    nar.warm = lambda: kicks.append(1)
    rc = r.Recap(nar, lambda m: ("Someone visited the Chair zone.", "m"))
    rc.observe(ev("enter", zone=2))
    reset = ev("reset", id="e9")
    rc.write(rc.observe(reset), reset)
    assert [m["event_kind"] for m in sent] == ["recap"] and kicks == [1]


def test_zones_come_from_nodes_json(tmp_path):
    saved = dict(n.ZONES)
    try:
        # the square's zones give the same prompt as before
        n.set_zones(dict(n.CONTRACT_ZONES))
        assert n.ZONES == {1: ("Bed", 60), 2: ("Chair", None), 3: ("Hall", None), 4: ("Bathroom", 10)}
        assert "The room has four zones: zone 1 (Bed), zone 2 (Chair), zone 3 (Hall) and zone 4 (Bathroom)." in n.system()
        assert n.examples()[0][2] == "Someone just stepped into zone 2, by the chair."
        # a new layout: its names reach the sentence, the alert limit and the prompt
        nodes = tmp_path / "nodes.json"
        nodes.write_text('{"zones": [{"id": 1, "name": "Desk", "still_alert_s": null},'
                         ' {"id": 2, "name": "Sofa", "still_alert_s": 8}]}')
        n.set_zones(n.load_zones(nodes))
        assert n.template("enter", {"zone": 2}) == "Someone just walked into zone 2 (Sofa)."
        assert n.template("alert_on", {"zone": 2}) == "No movement in zone 2 (Sofa) for 8 seconds; time to check in."
        assert "The room has two zones: zone 1 (Desk) and zone 2 (Sofa)." in n.system()
        assert r.facts([ev("enter", zone=1)]) == ["0:00 someone walked into the Desk zone"]
        # unreadable -> the contract's zones
        assert n.load_zones(tmp_path / "missing.json") == n.CONTRACT_ZONES
    finally:
        n.set_zones(saved)
