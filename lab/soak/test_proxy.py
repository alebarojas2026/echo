"""The chaos proxy does what the soak report says it did.  python -m pytest lab/soak"""
import json
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from proxy import ChaosProxy  # noqa: E402


def rig(**faults):
    bus = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    bus.bind(("127.0.0.1", 0))
    bus.settimeout(0.3)
    proxy = ChaosProxy(("127.0.0.1", 0), bus.getsockname())
    proxy.set_packets(**faults)
    proxy.start()
    sim = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(**msg):
        sim.sendto(json.dumps({"v": 2, **msg}).encode(), proxy.rx.getsockname())

    def received():
        got = []
        try:
            while True:
                got.append(json.loads(bus.recv(65535)))
        except socket.timeout:
            return got
    return proxy, send, received


def test_clean_proxy_forwards_everything_in_order():
    proxy, send, received = rig()
    for i in range(20):
        send(type="rssi", seq=i, link="east>pi5:ble", dbm=-60)
    assert [m["seq"] for m in received()] == list(range(20))
    proxy.stop()


def test_drop_dup_and_jitter():
    proxy, send, received = rig(drop=1.0)
    send(type="rssi", seq=1, link="east>pi5:ble", dbm=-60)
    assert received() == [] and proxy.counts["dropped"] == 1
    proxy.set_packets(dup=1.0, jitter_ms=50)
    send(type="rssi", seq=2, link="east>pi5:ble", dbm=-60)
    time.sleep(0.1)
    assert [m["seq"] for m in received()] == [2, 2]
    proxy.stop()


def test_silent_link_and_unplugged_camera():
    proxy, send, received = rig()
    proxy.silence("east>pi5:ble", 0.5)
    proxy.camera(False)
    send(type="rssi", seq=1, link="east>pi5:ble", dbm=-60)
    send(type="rssi", seq=2, link="west>pi5:ble", dbm=-60)
    send(type="label", seq=3)
    send(type="cam", seq=4, state="on", fps=7.5)
    got = received()
    assert [m.get("seq") for m in got if m["type"] == "rssi"] == [2]
    assert [m["state"] for m in got if m["type"] == "cam"] == ["off"]
    assert not any(m["type"] == "label" for m in got)
    time.sleep(0.5)
    proxy.camera(True)
    send(type="rssi", seq=5, link="east>pi5:ble", dbm=-60)
    assert [m["seq"] for m in received()] == [5]
    proxy.stop()
