import asyncio
import io
import json
import time

import pytest

from narrator import narrate as n

NOW = 1_763_149_512_200
FULL_INFO = {"zone": 4, "node": "pi5", "link": "east>pi5:ble", "before_dbm": -71.2,
             "after_dbm": -63.4, "limit_s": 10}


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


# ---------------------------------------------------------------- rate limit

def test_at_most_one_sentence_every_8_s():
    clock = Clock()
    nar, sent = make(clock=clock)
    nar.observe(event(id="e1"))
    assert nar.step()["event_id"] == "e1"

    clock.t = NOW + 6000
    nar.observe(event(t=clock.t, id="e2"))
    clock.t = NOW + 7999
    assert nar.step() is None            # still inside the 8 s gap
    clock.t = NOW + 8000
    assert nar.step()["event_id"] == "e2"  # waited, still fresh
    assert len(sent) == 2


def test_event_that_goes_stale_during_the_gap_is_dropped():
    clock = Clock()
    nar, sent = make(clock=clock)
    nar.observe(event(id="e1"))
    nar.step()
    clock.t = NOW + 1000
    nar.observe(event(t=clock.t, id="e2"))
    clock.t = NOW + 8000                  # gap over, but e2 is 7 s old
    assert nar.step() is None
    assert nar.pending is None
    assert [m["event_id"] for m in sent] == ["e1"]


def test_newest_event_wins():
    nar, sent = make()
    nar.observe(event(id="e1"))
    nar.observe(event(id="e2", kind="zone_change", info={"zone": 3}))
    nar.step()
    assert [m["event_id"] for m in sent] == ["e2"]


def test_unknown_kinds_and_other_messages_are_ignored():
    nar, sent = make()
    nar.observe(event(kind="party"))
    nar.observe({"v": 2, "type": "state", "t": NOW, "cam": "on"})
    assert nar.step() is None and sent == []


# ---------------------------------------------------------------- age cutoff

def test_event_3_s_old_is_narrated():
    nar, sent = make(clock=Clock(NOW + 3000))
    nar.observe(event())
    assert nar.step() is not None


def test_event_older_than_3_s_is_dropped():
    nar, sent = make(clock=Clock(NOW + 3001))
    nar.observe(event())
    assert nar.step() is None
    assert nar.pending is None and sent == []


def test_event_without_a_time_is_dropped():
    nar, sent = make()
    e = event()
    del e["t"]
    nar.observe(e)
    assert nar.step() is None and sent == []


# ---------------------------------------------------------------- 16-word cap

def test_16_words_from_the_model_is_fine():
    words = "Someone just walked into zone 2 and is now moving slowly around the room over there."
    assert len(words.split()) == 16
    nar, sent = make(words)
    nar.observe(event())
    assert nar.step()["source"] == "llm"


def test_17_words_from_the_model_falls_back_to_the_template():
    words = "Someone just walked into zone 2 and is now moving slowly around the room over there today."
    assert len(words.split()) == 17
    nar, sent = make(words)
    nar.observe(event())
    msg = nar.step()
    assert msg["source"] == "template"
    assert msg["text"] == "Someone just walked into zone 2 (Chair)."


@pytest.mark.parametrize("kind", n.EVENT_KINDS)
@pytest.mark.parametrize("info", [{}, FULL_INFO, {"zone": 1}, {"zone": 3, "link": "pi5>unoq:wifi"}])
def test_every_kind_has_a_short_clean_template(kind, info):
    text = n.template(kind, info)
    assert text and text[-1] in ".!?"
    assert len(text.split()) <= n.MAX_WORDS
    assert not n.BANNED.search(text)
    assert n.problem(text, text, camera_off=kind not in ("cam_on", "cam_stalled")) is None


def test_templates_use_zone_names_and_no_movement_wording():
    assert n.template("enter", {"zone": 1}) == "Someone just walked into zone 1 (Bed)."
    assert "zone 3 (Hall)" in n.template("zone_change", {"zone": 3})
    alert = n.template("alert_on", {"zone": 4})
    assert alert == "No movement in zone 4 (Bathroom) for 10 seconds; time to check in."
    assert "60 seconds" in n.template("alert_on", {"zone": 1})
    assert "-71 to -63 dBm" in n.template("advice_result", FULL_INFO)
    assert n.template("party", {}) is None


# ---------------------------------------------------------------- banned words

@pytest.mark.parametrize("reply", [
    "Someone fell down in zone 2.",
    "Someone may have fallen in zone 2.",
    "Someone could fall in zone 2.",
    "Radio Sight sees through walls in zone 2.",
    "Great home security for zone 2.",
    "The NPU spotted someone in zone 2.",
    "She just walked into zone 2.",
    "A man just walked into zone 2.",
    "Someone looks unwell in zone 2.",
    "Someone is sleeping in zone 2.",
])
def test_banned_words_fall_back_to_the_template(reply):
    nar, sent = make(reply)
    nar.observe(event())
    msg = nar.step()
    assert msg["source"] == "template" and msg["model"] is None
    assert msg["text"] == n.template("enter", {"zone": 2})


def test_camera_is_banned_after_cam_off():
    nar, sent = make("The camera is off now.")
    nar.observe(event(kind="cam_off", info={}))
    msg = nar.step()
    assert msg["source"] == "template"
    assert "camera" not in msg["text"].lower()


def test_camera_is_banned_when_the_brain_says_it_is_off():
    nar, sent = make("The camera saw someone enter zone 2.")
    nar.observe({"v": 2, "type": "state", "t": NOW, "cam": "off"})
    nar.observe(event())
    assert nar.step()["source"] == "template"


def test_camera_is_fine_while_it_is_on():
    nar, sent = make("The camera is on and teaching the radio.")
    nar.observe(event(kind="cam_on", info={}))
    assert nar.step()["source"] == "llm"


def test_made_up_numbers_fall_back_to_the_template():
    nar, sent = make("Someone just walked into zone 3.")
    nar.observe(event())  # zone 2
    assert nar.step()["source"] == "template"


def test_clean_keeps_one_plain_sentence():
    assert n.clean('  "Someone walked in." Then they sat.  ') == "Someone walked in."
    assert n.clean("Someone walked in \U0001F44B") == "Someone walked in."
    assert n.clean("It’s zone 2") == "It's zone 2."
    assert n.clean("") == ""


# ---------------------------------------------------------------- timeout and errors

def test_slow_model_falls_back_to_the_template():
    def slow(msgs):
        time.sleep(1.0)
        return "Someone just walked into zone 2.", "test-model"

    nar, sent = make(slow, clock=n.now_ms, timeout_s=0.1)
    nar.observe(event(t=n.now_ms()))
    msg = nar.step()
    assert msg["source"] == "template"
    assert 100 <= msg["gen_ms"] < 900


def test_unreachable_model_falls_back_to_the_template():
    def down(msgs):
        raise ConnectionRefusedError("connection refused")

    nar, sent = make(down)
    nar.observe(event())
    msg = nar.step()
    assert msg["source"] == "template" and msg["text"] == n.template("enter", {"zone": 2})


def test_default_timeout_is_8_s():
    assert n.LLM_TIMEOUT_S == 8.0 and n.Narrator(None, None).timeout_s == 8.0


# ---------------------------------------------------------------- message shape

def test_narration_message_matches_the_contract():
    nar, sent = make()
    nar.observe(event(id="e123", src="sim"))
    msg = nar.step()
    assert sent == [msg]
    assert set(msg) == {"v", "type", "t", "seq", "src", "text", "event_id", "event_kind",
                        "gen_ms", "source", "model"}
    assert msg["v"] == 2 and msg["type"] == "narration"
    assert msg["t"] == NOW and msg["seq"] == 1 and msg["src"] == "sim"
    assert msg["event_id"] == "e123" and msg["event_kind"] == "enter"
    assert msg["source"] == "llm" and msg["model"] == "test-model"
    assert isinstance(msg["gen_ms"], int) and msg["gen_ms"] >= 0
    assert json.loads(json.dumps(msg)) == msg


def test_seq_goes_up_by_one_per_message():
    clock = Clock()
    nar, sent = make(clock=clock)
    for i in range(3):
        clock.t = NOW + i * 8000
        nar.observe(event(t=clock.t, id=f"e{i}"))
        nar.step()
    assert [m["seq"] for m in sent] == [1, 2, 3]


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

class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_urlopen(reply, seen):
    def urlopen(req, timeout):
        seen.update(url=req.full_url, body=json.loads(req.data), timeout=timeout)
        return FakeResponse(json.dumps(reply).encode())
    return urlopen


def test_llama_client_asks_for_a_short_cool_reply(monkeypatch):
    seen = {}
    reply = {"model": "qwen", "choices": [{"finish_reason": "stop", "message": {"content": "Hi."}}]}
    monkeypatch.setattr(n.urllib.request, "urlopen", fake_urlopen(reply, seen))
    assert n.LlamaServer("http://127.0.0.1:8091")([{"role": "user", "content": "x"}]) == ("Hi.", "qwen")
    assert seen["url"] == "http://127.0.0.1:8091/v1/chat/completions"
    assert seen["body"]["max_tokens"] <= 48 and seen["body"]["temperature"] <= 0.3
    assert seen["timeout"] == 8.0


def test_llama_client_drops_a_cut_off_reply(monkeypatch):
    reply = {"model": "qwen", "choices": [{"finish_reason": "length", "message": {"content": "Someone"}}]}
    monkeypatch.setattr(n.urllib.request, "urlopen", fake_urlopen(reply, {}))
    assert n.LlamaServer()([]) == ("", "qwen")


def test_prompt_keeps_a_fixed_prefix_and_puts_the_event_last():
    a = n.prompt("enter", n.template("enter", {"zone": 2}))
    b = n.prompt("alert_on", n.template("alert_on", {"zone": 4}))
    assert a[:-1] == b[:-1]
    assert b[-1] == {"role": "user", "content": "Event: alert_on. Facts: " + n.template("alert_on", {"zone": 4})}


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
