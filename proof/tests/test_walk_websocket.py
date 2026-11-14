"""Real WebSocket frames, handshake and ping/pong over a local socket pair."""

import inspect
import json
import socket
import threading
from types import SimpleNamespace

import pytest
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK
from websockets.frames import Close
from websockets.server import ServerProtocol
from websockets.sync.client import connect
from websockets.sync.server import ServerConnection

from proof.walk import coach, drain_states


def normal_stop_close(error, commands):
    return (isinstance(error, ConnectionClosedOK) and error.rcvd is not None
            and error.rcvd.code == 1000 and bool(commands)
            and commands[-1]["cmd"] == "record_stop")


def test_state_flood_does_not_starve_ping_or_record_stop():
    # Connected local sockets need no listening port or network access.
    server_sock, client_sock = socket.socketpair()
    commands, errors = [], []
    drained = threading.Event()

    def serve():
        options = {"close_timeout": 1}
        if "server" in inspect.signature(ServerConnection).parameters:
            options["server"] = SimpleNamespace(socket_closed=threading.Event())
        ws = ServerConnection(server_sock, ServerProtocol(), **options)
        try:
            ws.handshake(timeout=2)
            for sequence in range(64):
                ws.send(json.dumps({"v": 2, "type": "state", "seq": sequence}))
            # Without draining, the default 16-frame queue prevents this pong.
            if not ws.ping(b"after-state-flood").wait(timeout=2):
                raise AssertionError("state backlog prevented the keepalive reply")
            drained.set()
            while True:
                command = json.loads(ws.recv(timeout=2))
                commands.append(command)
                if command["cmd"] == "record_stop":
                    break
                try:
                    ws.send(json.dumps({"v": 2, "type": "state"}))
                except ConnectionClosedOK as error:
                    if error.rcvd is None or error.rcvd.code != 1000:
                        raise
                    # A clean close can overtake replies while received commands
                    # remain queued. Keep reading; only record_stop is success.
        except Exception as error:
            if not normal_stop_close(error, commands):
                errors.append(error)
        finally:
            ws.close()

    server = threading.Thread(target=serve, daemon=True)
    server.start()
    options = {"sock": client_sock, "compression": None, "close_timeout": 1}
    if "proxy" in inspect.signature(connect).parameters:
        options["proxy"] = None
    try:
        with connect("ws://127.0.0.1/ws", **options) as ws:
            with drain_states(ws):
                assert drained.wait(timeout=3), errors
                now = [0]
                def sleep(seconds):
                    now[0] += seconds
                coach("socket-walk", "train", "w1", lambda msg: ws.send(json.dumps(msg)),
                      lambda _: None, sleep, lambda: now[0])
    finally:
        client_sock.close()
        server.join(timeout=3)
    assert not server.is_alive()
    assert not errors, errors
    assert len(commands) == 13
    assert commands[-2]["args"] == {"mode": "off"}
    assert commands[-1]["cmd"] == "record_stop"


def test_clean_close_is_only_accepted_after_record_stop():
    closed = ConnectionClosedOK(Close(1000, ""), Close(1000, ""), True)
    assert normal_stop_close(closed, [{"cmd": "record_stop"}])
    assert not normal_stop_close(closed, [])
    assert not normal_stop_close(closed, [{"cmd": "label_mode"}])


@pytest.mark.parametrize("error", [
    TimeoutError("keepalive reply timed out"),
    ConnectionClosedError(Close(1011, "keepalive ping timeout"), Close(1011, ""), True),
])
def test_timeouts_and_abnormal_closes_are_always_failures(error):
    assert not normal_stop_close(error, [{"cmd": "record_stop"}])
