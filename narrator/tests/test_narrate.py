import asyncio
import io
import json
import time

import pytest

from narrator import narrate as n

NOW = 1_763_149_512_200
FULL_INFO = {"zone": 4, "node": "pi5", "link": "east>pi5:ble", "before_dbm": -71.2,
             "after_dbm": -63.4, "limit_s": 10}
ENTER_2 = "Someone just walked into zone 2 (Chair)."


class Clock:
    def __init__(self, t=NOW):
        self.t = t

    def __call__(self):
        return self.t


def event(kind="enter", t=NOW, info=None, id="e1", src="live"):
    return {"v": 2, "type": "event", "t": t, "seq": 1, "src": src, "id": id, "kind": kind,
            "info": {"zone": 2} if info is None else info}


def make(reply="Someone just stepped into zone 2.", clock=None, **kw):
    """A narrator with a fake model that always says `reply` (or calls it)."""
    sent = []
    llm = reply if callable(reply) else (lambda msgs: (reply, "test-model"))
    return n.Narrator(llm, sent.append, clock=clock or Clock(), **kw), sent


def one(reply, *messages, **kw):
    """Narrate the last of `messages` with a fake model saying `reply`."""
    nar, sent = make(reply, **kw)
    for m in messages:
        nar.observe(m)
    return nar.step()


# ---------------------------------------------------------------- rate limit

def test_at_most_one_sentence_every_8_s():
    clock = Clock()
    nar, sent = make(clock=clock)
    nar.observe(event(id="e1"))
    nar.step()
    clock.t = NOW + 6000
    nar.observe(event(t=clock.t, id="e2"))
    clock.t = NOW + 7999
    assert nar.step() is None               # inside the 8 s gap
    clock.t = NOW + 8000
    assert nar.step()["event_id"] == "e2"   # waited, still fresh
    assert [m["seq"] for m in sent] == [1, 2]


def test_event_that_goes_stale_during_the_gap_is_dropped():
    clock = Clock()
    nar, sent = make(clock=clock)
    nar.observe(event(id="e1"))
    nar.step()
    clock.t = NOW + 1000
    nar.observe(event(t=clock.t, id="e2"))
    clock.t = NOW + 8000                     # gap over, but e2 is 7 s old
    assert nar.step() is None and nar.pending is None
    assert [m["event_id"] for m in sent] == ["e1"]


def test_newest_event_wins_and_other_messages_are_ignored():
    msg = one("Someone moved to zone 3.", event(id="e1"),
              event(id="e2", kind="zone_change", info={"zone": 3}),
              event(id="e3", kind="party"), {"v": 2, "type": "state", "t": NOW, "cam": "on"})
    assert msg["event_id"] == "e2"


# ---------------------------------------------------------------- age cutoff

@pytest.mark.parametrize("age_ms, narrated", [(0, True), (3000, True), (3001, False), (None, False)])
def test_only_events_up_to_3_s_old(age_ms, narrated):
    e = event(t=None if age_ms is None else NOW - age_ms)
    nar, sent = make()
    nar.observe(e)
    assert (nar.step() is not None) == narrated
    assert nar.pending is None and len(sent) == narrated


# ---------------------------------------------------------------- 16-word cap

@pytest.mark.parametrize("extra, source", [("", "llm"), (" today", "template")])
def test_16_words_from_the_model_is_the_limit(extra, source):
    words = f"Someone just walked into zone 2 and is now moving slowly around the room over there{extra}."
    msg = one(words, event())
    assert msg["source"] == source
    assert len(msg["text"].split()) <= 16


@pytest.mark.parametrize("kind", n.EVENT_KINDS)
@pytest.mark.parametrize("info", [{}, FULL_INFO, {"zone": 1}, {"zone": 3, "link": "pi5>unoq:wifi"}])
def test_every_kind_has_a_short_clean_template(kind, info):
    text = n.template(kind, info)
    assert text and text[-1] in ".!?"
    assert n.problem(text, text, camera_off=kind not in ("cam_on", "cam_stalled")) is None


def test_templates_use_zone_names_and_no_movement_wording():
    assert n.template("enter", {"zone": 1}) == "Someone just walked into zone 1 (Bed)."
    assert "zone 3 (Hall)" in n.template("zone_change", {"zone": 3})
    assert n.template("alert_on", {"zone": 4}) == \
        "No movement in zone 4 (Bathroom) for 10 seconds; time to check in."
    assert "60 seconds" in n.template("alert_on", {"zone": 1})
    assert "-71 to -63 dBm" in n.template("advice_result", FULL_INFO)
    assert n.template("party", {}) is None


# ---------------------------------------------------------------- banned words

@pytest.mark.parametrize("reply", [
    "Someone fell down in zone 2.", "Someone may have fallen in zone 2.",
    "Someone could fall in zone 2.", "Radio Sight sees through walls in zone 2.",
    "Great home security for zone 2.", "The NPU spotted someone in zone 2.",
    "She just walked into zone 2.", "A man just walked into zone 2.",
    "Someone looks unwell in zone 2.", "Someone is sleeping in zone 2.",
    "Someone just walked into zone 3.",   # made-up number
])
def test_banned_words_fall_back_to_the_template(reply):
    msg = one(reply, event())
    assert (msg["source"], msg["model"], msg["text"]) == ("template", None, ENTER_2)


@pytest.mark.parametrize("before, ev, reply, source", [
    ([], event(kind="cam_off", info={}), "The camera is off now.", "template"),
    ([{"type": "state", "cam": "off"}], event(), "The camera saw someone in zone 2.", "template"),
    ([], event(kind="cam_on", info={}), "The camera is on and teaching the radio.", "llm"),
])
def test_camera_is_banned_once_it_is_off(before, ev, reply, source):
    msg = one(reply, *before, ev)
    assert msg["source"] == source
    if ev["kind"] == "cam_off":
        assert "camera" not in msg["text"].lower()


def test_clean_keeps_one_plain_sentence():
    assert n.clean('  "Someone walked in." Then they sat.  ') == "Someone walked in."
    assert n.clean("Someone walked in \U0001F44B") == "Someone walked in."
    assert n.clean("It\u2019s zone 2") == "It's zone 2."
    assert n.clean("") == ""


# ---------------------------------------------------------------- timeout and errors

def test_slow_model_falls_back_to_the_template():
    def slow(msgs):
        time.sleep(1.0)
        return "Someone just walked into zone 2.", "test-model"

    msg = one(slow, event(t=n.now_ms()), clock=n.now_ms, timeout_s=0.1)
    assert (msg["source"], msg["text"]) == ("template", ENTER_2)
    assert 100 <= msg["gen_ms"] < 900
    assert n.Narrator(None, None).timeout_s == 8.0


def test_unreachable_model_falls_back_to_the_template():
    def down(msgs):
        raise ConnectionRefusedError("connection refused")

    msg = one(down, event())
    assert (msg["source"], msg["text"]) == ("template", ENTER_2)


# ---------------------------------------------------------------- message shape

def test_narration_message_matches_the_contract():
    nar, sent = make()
    nar.observe(event(id="e123", src="sim"))
    msg = nar.step()
    assert sent == [msg] and json.loads(json.dumps(msg)) == msg
    assert msg == {"v": 2, "type": "narration", "t": NOW, "seq": 1, "src": "sim",
                   "text": "Someone just stepped into zone 2.", "event_id": "e123",
                   "event_kind": "enter", "gen_ms": 0, "source": "llm", "model": "test-model"}


def test_udp_sender_sends_one_compact_json_datagram(monkeypatch):
    sent = []

    class FakeSocket:
        def __init__(self, *args):
            pass

        def sendto(self, data, addr):
            sent.append((data, addr))

    monkeypatch.setattr(n.socket, "socket", FakeSocket)
    n.udp_sender("127.0.0.1:5600")({"v": 2, "type": "narration"})
    assert sent == [(b'{"v":2,"type":"narration"}', ("127.0.0.1", 5600))]


# ---------------------------------------------------------------- model client and prompt

@pytest.mark.parametrize("finish, text", [("stop", "Hi."), ("length", "")])
def test_llama_client_asks_for_a_short_cool_reply(monkeypatch, finish, text):
    seen = {}

    def urlopen(req, timeout):
        seen.update(url=req.full_url, body=json.loads(req.data), timeout=timeout)
        reply = {"model": "qwen", "choices": [{"finish_reason": finish, "message": {"content": "Hi."}}]}
        return io.BytesIO(json.dumps(reply).encode())

    monkeypatch.setattr(n.urllib.request, "urlopen", urlopen)
    assert n.LlamaServer("http://127.0.0.1:8091")([]) == (text, "qwen")
    assert seen["url"] == "http://127.0.0.1:8091/v1/chat/completions"
    assert seen["body"]["max_tokens"] <= 48 and seen["body"]["temperature"] <= 0.3
    assert seen["timeout"] == 8.0


def test_prompt_keeps_a_fixed_prefix_and_puts_the_event_last():
    a = n.prompt("enter", ENTER_2)
    b = n.prompt("alert_on", n.template("alert_on", {"zone": 4}))
    assert a[:-1] == b[:-1]
    assert b[-1]["content"] == "Event: alert_on. Facts: " + n.template("alert_on", {"zone": 4})


# ---------------------------------------------------------------- the loop, with a fake feed

def test_serve_narrates_events_from_a_fake_feed():
    async def feed():
        yield {"v": 2, "type": "state", "t": n.now_ms(), "cam": "on"}
        yield event(t=n.now_ms(), id="e1")
        yield event(t=n.now_ms(), id="e2", kind="zone_change", info={"zone": 4})

    nar, sent = make("Someone moved over to zone 4.", clock=n.now_ms)
    asyncio.run(n.serve(feed(), nar, poll_s=0.01))
    assert [(m["event_id"], m["source"], m["text"]) for m in sent] == [
        ("e2", "llm", "Someone moved over to zone 4.")]
