import asyncio
import time

import pytest

from narrator import narrate as n
from narrator import recap as r

NOW = 1_763_149_512_000


def ev(seconds, kind, id=None, **info):
    return {"v": 2, "type": "event", "t": NOW + round(seconds * 1000), "seq": 1, "src": "live",
            "id": id or f"e{seconds}", "kind": kind, "info": info}


# A full demo, in runbook order, as the brain reports it.
DEMO = [ev(0, "enter", zone=3), ev(6, "zone_change", zone=4), ev(12, "zone_change", zone=2),
        ev(18, "zone_change", zone=4), ev(29, "alert_on", zone=4), ev(33, "checkin", zone=4, link="pi5>unoq:wifi"),
        ev(34, "alert_off", zone=4), ev(40, "cam_off"), ev(52, "exit", zone=4), ev(60, "object_on", node="pi5"),
        ev(65, "advice", node="pi5", link="pi5>unoq:wifi"), ev(72, "router_moved"),
        ev(77, "advice_result", link="pi5>unoq:wifi", before_dbm=-71.2, after_dbm=-63.4),
        ev(80, "object_off", node="pi5"), ev(84, "router_home"), ev(85, "baseline_done"), ev(86, "recording", on=False)]
RESET = ev(95, "reset", id="e99")
GOOD = "Someone toured the Hall, Bathroom and Chair zones. A no-movement alert fired and a wave answered it. Moving the router lifted its Wi-Fi from -71 to -63 dBm."


def make(reply=GOOD, **kw):
    sent, clock = [], [NOW + 95_000]
    nar = n.Narrator(lambda m: ("", None), sent.append, clock=lambda: clock[0])
    llm = reply if callable(reply) else (lambda msgs: (reply, "test-model"))
    return r.Recap(nar, llm, **kw), nar, sent


def run(reply=GOOD, events=DEMO, **kw):
    rc, nar, sent = make(reply, **kw)
    for e in events:
        nar.observe(e)
        assert rc.observe(e) is None
    kept = rc.observe(RESET)
    return rc.write(kept, RESET) if kept else None, sent


def test_fact_list_for_a_full_demo():
    assert r.facts(DEMO) == [
        "0:00 someone walked into the Hall zone", "0:06 someone moved to the Bathroom zone",
        "0:12 someone moved to the Chair zone", "0:18 someone moved to the Bathroom zone",
        "0:29 no-movement alert in the Bathroom zone", "0:33 a wave check-in was received",
        "0:40 setup ended and sensing carried on by radio alone", "0:52 someone left the room",
        "1:00 a new object appeared near the router", "1:05 the board advised moving the router",
        "1:12 the router was moved", "1:17 after the move the router's Wi-Fi went from -71 to -63 dBm",
        "1:20 the object was taken away", "1:24 the router went back to its home spot"]


def test_dbm_only_comes_from_advice_result():
    lines = r.facts([ev(0, "enter", zone=2, before_dbm=-50), ev(3, "advice", before_dbm=-71.2),
                     ev(5, "advice_result", before_dbm=-71.2)])
    assert lines == ["0:00 someone walked into the Chair zone", "0:03 the board advised moving the router"]


def test_model_recap_goes_out_as_a_narration():
    seen = []
    msg, sent = run(lambda msgs: (seen.append(msgs), (GOOD, "test-model"))[1])
    assert sent == [msg]
    assert (msg["text"], msg["source"], msg["model"], msg["event_kind"], msg["event_id"]) == (
        GOOD, "llm", "test-model", "recap", "e99")
    assert (msg["v"], msg["type"], msg["seq"], msg["src"], msg["t"]) == (2, "narration", 1, "live", NOW + 95_000)
    assert msg["gen_ms"] >= 0 and set(msg) == {"v", "type", "t", "seq", "src", "text", "event_id", "event_kind",
                                               "gen_ms", "source", "model"}
    assert seen[0][-1]["content"].splitlines()[1:] == r.facts(DEMO)


def test_template_recap_fits_the_limits_and_uses_only_the_facts():
    text = r.template(DEMO)
    assert text == ("Someone visited the Hall, Bathroom and Chair zones. "
                    "A no-movement alert fired in the Bathroom zone and a wave check-in answered it. "
                    "Moving the router took its Wi-Fi from -71 to -63 dBm.")
    assert r.problem(text, r.facts(DEMO), camera_off=True) is None
    for cut in range(1, len(DEMO) + 1):   # any shorter demo also gives a recap that passes its own checks
        part = DEMO[:cut]
        assert r.problem(r.template(part), r.facts(part), camera_off=True) is None, cut
    assert r.template([ev(0, "baseline_done")]) is None


@pytest.mark.parametrize("reply, why", [
    (" ".join(["word"] * 46) + ".", "too long"),
    ("One. Two. Three. Four.", "too many sentences"),
    ("Someone fell in the Bathroom zone.", "banned word"),
    ("She toured the zones.", "banned word"),
    ("The camera watched someone tour the zones.", "banned word"),
    ("Moving the router lifted its Wi-Fi from -71 to -58 dBm.", "made-up number"),
    ("Someone visited 4 zones in 95 seconds.", "made-up number"),
    ("", "empty"),
])
def test_bad_model_recap_falls_back_to_the_template(reply, why):
    assert r.problem(r.clean(reply), r.facts(DEMO), camera_off=True) == why
    msg, _ = run(reply)
    assert (msg["text"], msg["source"], msg["model"]) == (r.template(DEMO), "template", None)


def test_45_words_and_3_sentences_are_the_limit():
    assert r.problem(" ".join(["word"] * 45) + ".", [], False) is None
    assert r.problem("One. Two. Three.", [], False) is None
    assert r.clean('  "Someone toured\nthe zones"  ') == "Someone toured the zones."


def test_slow_or_unreachable_model_falls_back_to_the_template():
    def slow(msgs):
        time.sleep(0.5)
        return GOOD, "test-model"

    def down(msgs):
        raise OSError("connection refused")

    for llm in (slow, down):
        msg, _ = run(llm, timeout_s=0.05)
        assert (msg["text"], msg["source"]) == (r.template(DEMO), "template")


def test_reset_starts_a_new_demo_and_an_empty_one_sends_nothing():
    rc, nar, sent = make()
    for e in DEMO[:3]:
        rc.observe(e)
    first = rc.observe(RESET)
    assert len(first) == 3 and rc.events == []
    assert rc.observe(ev(100, "reset")) is None                      # nothing happened since
    assert rc.observe(ev(101, "baseline_done")) is None and rc.observe(ev(102, "reset")) is None   # nothing worth telling
    assert rc.observe({"v": 2, "type": "state", "t": NOW}) is None and rc.events == []


def test_recap_shares_the_narrators_seq_counter():
    rc, nar, sent = make()
    nar.observe(ev(95, "enter", zone=2))
    nar.step()
    rc.observe(DEMO[0])
    rc.write(rc.observe(RESET), RESET)
    assert [(m["event_kind"], m["seq"]) for m in sent] == [("enter", 1), ("recap", 2)]


def test_serve_writes_the_recap_when_the_reset_arrives():
    async def feed():
        for e in DEMO:
            yield dict(e, t=n.now_ms() - 10_000)   # too old for the per-event narrator
        yield RESET

    sent = []
    nar = n.Narrator(lambda m: ("", None), sent.append)
    asyncio.run(n.serve(feed(), nar, poll_s=0.01, recap=r.Recap(nar, lambda m: (GOOD, "test-model"))))
    assert [(m["event_kind"], m["text"]) for m in sent] == [("recap", GOOD)]


class FakeTime:
    """A clock whose sleep moves it forward, so the 8 s spacing is checked without waiting."""

    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += round(seconds * 1000)


def test_recap_keeps_the_8_s_spacing_on_both_sides():
    clock, sent = FakeTime(NOW), []
    nar = n.Narrator(lambda m: ("Someone just stepped into zone 2.", "test-model"), sent.append,
                     clock=clock, sleep=clock.sleep)
    rc = r.Recap(nar, lambda m: (GOOD, "test-model"))
    first = ev(0, "enter", zone=2)
    nar.observe(first)
    rc.observe(first)
    nar.step()                                    # a sentence at 0 s
    clock.t = NOW + 1000
    reset = dict(RESET, t=clock.t)
    rc.write(rc.observe(reset), reset)            # the reset a second later: the recap waits for 8 s
    clock.t = NOW + 9000
    nar.observe(ev(9, "enter", id="e9", zone=3))  # the next judge walks in at 9 s
    nar.step()
    assert [(m["event_kind"], m["t"] - NOW, m["seq"]) for m in sent] == [
        ("enter", 0, 1), ("recap", 8000, 2), ("enter", 16000, 3)]


def test_recap_and_sentence_on_two_threads_never_share_a_seq_or_the_gap():
    import threading

    sent = []
    nar = n.Narrator(lambda m: ("Someone just stepped into zone 2.", "test-model"), sent.append,
                     gap_ms=200)
    rc = r.Recap(nar, lambda m: (GOOD, "test-model"))
    rc.observe(DEMO[0])
    events = rc.observe(RESET)
    threads = [threading.Thread(target=nar.narrate, args=(ev(0, "enter", zone=2),)) for _ in range(3)]
    threads.append(threading.Thread(target=rc.write, args=(events, RESET)))
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert sorted(m["seq"] for m in sent) == [1, 2, 3, 4]
    times = sorted(m["t"] for m in sent)
    assert all(b - a >= 200 for a, b in zip(times, times[1:]))
