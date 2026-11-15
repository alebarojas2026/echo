"""board/clock.py: the endpoint's rules with a fake brain and clock, the helper with a fake clock
setter and systemctl, and GET/POST /clock through serve.py."""
import asyncio
import json
import socket
import subprocess
import threading
import urllib.error
import urllib.request

import pytest

from board import clock, serve

NOW = 1_763_149_500_000
IDLE = {"type": "state", "t": NOW, "model": {"trained": True, "training": None}}


@pytest.fixture
def api(tmp_path):
    run, sessions = tmp_path / "run", tmp_path / "sessions"
    run.mkdir()
    sessions.mkdir()
    (run / "ready.json").write_text(json.dumps({"t": NOW}))
    a = clock.ClockAPI(run_dir=run, sessions=sessions, state=lambda: dict(IDLE), now=lambda: NOW)
    a.dirs = run, sessions
    return a


def post(api, t):
    return api.post(json.dumps({"t": t}).encode())


def test_within_2_s_nothing_happens(api):
    assert post(api, NOW + 2000) == (200, {"ok": True, "diff_ms": 2000, "stepping": False})
    assert not (api.dirs[0] / "request.json").exists()


def test_more_than_2_s_off_hands_the_step_to_the_helper(api):
    status, doc = post(api, NOW + 520_000)
    assert (status, doc) == (202, {"ok": True, "diff_ms": 520_000, "stepping": True})
    assert json.loads((api.dirs[0] / "request.json").read_text()) == {"offset_ms": 520_000, "asked_t": NOW}


@pytest.mark.parametrize("body", [b"", b"nope", b'{"t": "now"}', b'{"t": 12}', b'{"t": true}', b'{"x": 1}'])
def test_a_bad_body_is_a_400(api, body):
    status, doc = api.post(body)
    assert status == 400 and doc["ok"] is False


def busy_case(api, case):
    run, sessions = api.dirs
    if case == "armed":
        api.state = lambda: {**IDLE, "armed": True}
        return "armed: disarm first"
    if case == "lesson":
        api.state = lambda: {**IDLE, "model": {"training": {"started_t": NOW, "lesson": {"fits": 1}}}}
        return "a lesson is running"
    if case == "fit":
        api.state = lambda: {**IDLE, "model": {"training": {"started_t": NOW, "progress": None}}}
        return "a fit is running"
    if case == "recording":
        (sessions / ".open").write_text(json.dumps({"session": "s07"}))
        return "a recording is open (s07)"
    if case == "baseline":
        (sessions / ".baseline").write_text(json.dumps({"asked_t": NOW - 30_000}))
        (sessions / "baseline.json").write_text(json.dumps({"t": NOW - 600_000}))
        return "a baseline is being captured"
    if case == "brain down":
        def down():
            raise clock.Unreadable("no")
        api.state = down
        return "the brain isn't answering"
    (run / "request.json").write_text("{}")
    return "a clock step is already under way"


@pytest.mark.parametrize("case", ["armed", "lesson", "fit", "recording", "baseline", "brain down", "step under way"])
def test_refused_while_anything_is_open(api, case):
    why = busy_case(api, case)
    assert api.get()[1]["busy"] == why
    status, doc = post(api, NOW + 520_000)
    assert (status, doc) == (409, {"ok": False, "diff_ms": 520_000, "why": why})
    if case != "step under way":
        assert not (api.dirs[0] / "request.json").exists()


def test_a_finished_or_given_up_baseline_does_not_block(api):
    _, sessions = api.dirs
    (sessions / ".baseline").write_text(json.dumps({"asked_t": NOW - 30_000}))
    (sessions / "baseline.json").write_text(json.dumps({"t": NOW - 5_000}))
    assert api.get()[1]["busy"] is None
    (sessions / "baseline.json").unlink()
    (sessions / ".baseline").write_text(json.dumps({"asked_t": NOW - clock.BASELINE_OPEN_MS - 1}))
    assert api.get()[1]["busy"] is None


@pytest.mark.parametrize("ready", [None, {"t": NOW - 6000}, "garbage"])
def test_no_helper_is_a_503(api, ready):
    run, _ = api.dirs
    if ready is None:
        (run / "ready.json").unlink()
    else:
        (run / "ready.json").write_text(json.dumps(ready) if isinstance(ready, dict) else ready)
    assert post(api, NOW + 520_000) == (503, {"ok": False, "why": clock.NO_HELPER})


def test_get_says_the_time_and_the_last_step(api):
    assert api.get() == (200, {"t": NOW, "busy": None, "last": None})
    (api.dirs[0] / "result.json").write_text(json.dumps({"ok": True, "t": NOW, "stepped_ms": 5, "took_s": 9.1}))
    assert api.get()[1]["last"]["took_s"] == 9.1


# ---- the helper ----

class Box:
    """A fake board: a clock that can be set, and units that start and stop."""

    def __init__(self, active):
        self.t, self.active, self.calls = NOW / 1000, set(active), []

    def clock(self):
        return self.t

    def set_clock(self, ms):
        self.calls.append(("set", ms))
        self.t = ms / 1000

    def systemctl(self, verb, *args):
        unit = args[-1].removesuffix(".service")
        if verb == "is-active":
            return subprocess.CompletedProcess(args, 0 if unit in self.active else 3)
        self.calls.append((verb, unit))
        if verb == "stop":
            self.active.discard(unit)
        else:
            self.active.add(unit)
        return subprocess.CompletedProcess(args, 0)


def helper(tmp_path, box):
    return clock.Helper(run_dir=tmp_path, systemctl=box.systemctl, set_clock=box.set_clock, clock=box.clock,
                        monotonic=lambda: 0.0)


def test_the_helper_stops_the_stack_sets_the_clock_and_starts_it_in_order(tmp_path):
    box = Box(["radio-sight-bus", "radio-sight-brain", "radio-sight-narrate", "radio-sight-camwatch"])
    (tmp_path / "request.json").write_text(json.dumps({"offset_ms": 520_000, "asked_t": NOW - 300}))
    result = helper(tmp_path, box).step_once()
    assert box.calls == [("stop", "radio-sight-narrate"), ("stop", "radio-sight-brain"),
                         ("stop", "radio-sight-camwatch"), ("stop", "radio-sight-bus"),
                         ("set", NOW + 520_000),
                         ("start", "radio-sight-bus"), ("start", "radio-sight-camwatch"),
                         ("start", "radio-sight-brain"), ("start", "radio-sight-narrate")]
    assert result["ok"] is True and result["stepped_ms"] == 520_000
    assert json.loads((tmp_path / "result.json").read_text()) == result
    assert not (tmp_path / "request.json").exists()
    assert helper(tmp_path, box).step_once() is None   # nothing asked: nothing done


def test_a_unit_that_was_off_stays_off(tmp_path):
    box = Box(["radio-sight-bus"])
    (tmp_path / "request.json").write_text(json.dumps({"offset_ms": -9000, "asked_t": NOW}))
    helper(tmp_path, box).step_once()
    assert ("start", "radio-sight-wifi-rssi") not in box.calls and box.active == {"radio-sight-bus"}


@pytest.mark.parametrize("req, why", [
    ({"offset_ms": 520_000, "asked_t": NOW - 60_000}, "too old"),
    ({"offset_ms": -NOW, "asked_t": NOW}, "out of range"),
    ({"offset_ms": "lots", "asked_t": NOW}, "be read"),
])
def test_the_helper_refuses_a_stale_or_odd_request_and_touches_nothing(tmp_path, req, why):
    box = Box(["radio-sight-bus"])
    (tmp_path / "request.json").write_text(json.dumps(req))
    result = helper(tmp_path, box).step_once()
    assert result["ok"] is False and why in result["why"] and box.calls == []


def test_a_clock_that_cant_be_set_still_starts_the_stack_again(tmp_path):
    box = Box(["radio-sight-bus", "radio-sight-brain"])

    def refuse(ms):
        raise PermissionError(1, "Operation not permitted")
    box.set_clock = refuse
    (tmp_path / "request.json").write_text(json.dumps({"offset_ms": 520_000, "asked_t": NOW}))
    result = helper(tmp_path, box).step_once()
    assert result["ok"] is False and "be set" in result["why"] and result["stepped_ms"] == 0
    assert box.active == {"radio-sight-bus", "radio-sight-brain"}


# ---- the brain's state, read the way the checks read it ----

def test_brain_state_reads_the_first_state_message():
    ws_server = pytest.importorskip("websockets.asyncio.server")
    big = {"type": "state", "t": NOW, "armed": True, "xray": {"moving_db": [0.5] * 5000}}

    async def talk(ws):
        await ws.send(json.dumps({"type": "event", "kind": "enter"}))
        await ws.send(json.dumps(big))
        await ws.wait_closed()

    async def main():
        async with ws_server.serve(talk, "127.0.0.1", 0) as srv:
            port = srv.sockets[0].getsockname()[1]
            return await asyncio.to_thread(clock.brain_state, "127.0.0.1", port, 3)

    assert asyncio.run(main()) == big


def test_brain_state_with_no_brain_is_unreadable():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with pytest.raises(clock.Unreadable, match="answering"):
        clock.brain_state("127.0.0.1", port, 1)


# ---- through serve.py ----

def test_get_and_post_clock_through_the_web_server(api, tmp_path):
    srv = serve.make_server("127.0.0.1", 0, dist=tmp_path, nodes=tmp_path / "n.json", proof=tmp_path / "p.json",
                            clock_api=api)
    threading.Thread(target=srv.serve_forever, args=(0.05,), daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/clock"
    try:
        with urllib.request.urlopen(base, timeout=5) as r:
            assert json.loads(r.read()) == {"t": NOW, "busy": None, "last": None}
        req = urllib.request.Request(base, data=json.dumps({"t": NOW + 520_000}).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            assert r.status == 202 and json.loads(r.read())["stepping"] is True
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(urllib.request.Request(base, data=b"x" * 300, method="POST"), timeout=5)
        assert e.value.code == 400
    finally:
        srv.shutdown()
        srv.server_close()
