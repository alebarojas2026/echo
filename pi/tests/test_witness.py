"""pi.witness: what it signs, what it refuses, its own log, its keys, and a bus that comes and goes.

The keys here are throwaway ones made in pytest's temp folder. The tests that need the real
`openssl` skip when there is none (or it is too old for Ed25519)."""
import base64
import json
import os
import shutil
import socket
import stat
import subprocess
import threading
import time

import pytest

from pi import witness as w

H1, H2, H3 = "a" * 64, "b" * 64, "c" * 64
T = 1763149512200


def head(seq, hash_=H1, t=T, **extra):
    return json.dumps({"v": 2, "type": "chain_head", "seq": seq, "hash": hash_, "t": t, **extra}).encode()


def fake_sign(data: bytes) -> bytes:
    return (data * 64)[:64]


@pytest.fixture
def wit(tmp_path):
    said = []
    one = w.Witness("pi5", fake_sign, w.SignedLog(tmp_path / "signed.jsonl"), say=said.append)
    one.said = said
    return one


def lines(wit):
    return [json.loads(line) for line in wit.log.path.read_text().splitlines()]


def test_signs_the_head_it_is_sent(wit):
    answer = json.loads(wit.head(head(12)))
    assert answer == {"v": 2, "type": "chain_witness", "node": "pi5", "seq": 12, "hash": H1, "t": T,
                      "sig": fake_sign(f"pi5|12|{H1}|{T}".encode()).hex(), "src": "live"}
    assert lines(wit) == [{"seq": 12, "hash": H1, "t": T, "sig": answer["sig"]}]
    assert "last seq signed 12, 1 signatures a minute" in wit.status_line()


@pytest.mark.parametrize("data", [
    b"not json", b"[]", b'{"type":"rssi"}', head(0), head(-3), head(1.5), head(True), head("7"),
    head(5, hash_="A" * 64), head(5, hash_="a" * 63), head(5, hash_=None), head(5, t=0), head(5, t="now"),
    json.dumps({"v": 2, "type": "chain_head", "seq": 5}).encode(),
])
def test_ignores_a_malformed_head(wit, data):
    assert wit.head(data) is None
    assert wit.ignored == 1 and not wit.log.path.exists()


def test_another_witness_answer_is_not_signed_or_counted(wit):
    assert wit.head(json.dumps({"v": 2, "type": "chain_witness", "node": "pi5b", "seq": 5}).encode()) is None
    assert wit.ignored == 0


def test_the_same_head_again_gets_the_same_answer_and_one_log_line(wit):
    assert wit.head(head(12)) == wit.head(head(12))
    assert len(lines(wit)) == 1


def test_a_step_back_is_logged_before_it_is_signed(wit):
    wit.head(head(12, H1))
    order = []
    sign, append = wit.sign, wit.log.append
    wit.sign = lambda data: order.append("sign") or sign(data)
    wit.log.append = lambda entry: order.append(("log", entry.get("back_from"))) or append(entry)
    answer = wit.head(head(7, H2))
    assert order == ["sign", ("log", {"seq": 12, "hash": H1})]      # logged before anything is returned to send
    assert json.loads(answer)["seq"] == 7
    assert lines(wit)[-1]["back_from"] == {"seq": 12, "hash": H1}
    assert any("stepped back" in line for line in wit.said) and wit.steps_back == 1
    wit.head(head(8, H3))
    assert "back_from" not in lines(wit)[-1]                        # forward again: an ordinary line


def test_the_same_seq_with_another_hash_is_a_step_back_too(wit):
    wit.head(head(12, H1))
    wit.head(head(12, H2))
    assert lines(wit)[-1]["back_from"] == {"seq": 12, "hash": H1}


def test_a_step_back_that_cannot_be_logged_is_not_signed(wit):
    wit.head(head(12, H1))

    def full(entry):
        raise OSError("No space left on device")
    wit.log.append = full
    assert wit.head(head(7, H2)) is None
    assert wit.failed == 1 and wit.last[0] == 12
    assert "not signing: No space left on device" in wit.status_line()


def test_a_restart_remembers_the_last_seq_from_its_own_log(wit):
    wit.head(head(12, H1))
    again = w.Witness("pi5", fake_sign, w.SignedLog(wit.log.path), say=lambda line: None)
    again.head(head(3, H2))
    assert lines(again)[-1]["back_from"] == {"seq": 12, "hash": H1}


def test_the_status_line_says_when_the_board_is_quiet(wit):
    assert "no head from the board yet" in wit.status_line(now=100.0)
    wit.head(head(12), now=100.0)
    assert "no head" not in wit.status_line(now=105.0)
    assert "no head from the board for 20 s" in wit.status_line(now=120.0)
    assert "0 signatures a minute" in wit.status_line(now=161.0)


# --- the real openssl -------------------------------------------------------------------------

def _openssl_signs() -> bool:
    if not shutil.which("openssl"):
        return False
    r = subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519"], capture_output=True)
    return r.returncode == 0


needs_openssl = pytest.mark.skipif(not _openssl_signs(), reason="needs an openssl that makes Ed25519 keys")


@pytest.fixture
def enrolled(tmp_path, monkeypatch):
    monkeypatch.setenv("WITNESS_DIR", str(tmp_path / "witness"))
    monkeypatch.delenv("RADIO_NODE", raising=False)
    monkeypatch.delenv("OPENSSL", raising=False)
    return tmp_path / "witness", w.init("pi5", tmp_path / "witness")


@needs_openssl
def test_openssl_signature_verifies_with_the_public_line(enrolled, tmp_path):
    where, line = enrolled
    node, body = json.loads("{" + line + "}").popitem()
    assert node == "pi5" and len(base64.b64decode(body)) == 44      # the DER public key: 12 + 32 bytes
    pub = tmp_path / "pub.pem"
    pub.write_text(f"-----BEGIN PUBLIC KEY-----\n{body}\n-----END PUBLIC KEY-----\n")
    one = w.Witness("pi5", w.Signer(where), w.SignedLog(where / w.LOG_NAME), say=lambda line: None)
    answer = json.loads(one.head(head(12)))
    assert len(answer["sig"]) == 128 and answer["sig"] == answer["sig"].lower()
    msg, sig = tmp_path / "msg.bin", tmp_path / "sig.bin"
    sig.write_bytes(bytes.fromhex(answer["sig"]))

    def verifies(data: bytes) -> bool:
        msg.write_bytes(data)
        return subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(pub), "-rawin",
                               "-in", str(msg), "-sigfile", str(sig)], capture_output=True).returncode == 0
    assert verifies(f"pi5|12|{H1}|{T}".encode())
    assert not verifies(f"pi5|13|{H1}|{T}".encode())
    assert not verifies(f"pi5b|12|{H1}|{T}".encode())


@needs_openssl
def test_init_prints_only_the_public_line_and_keeps_the_key_private(enrolled, capsys):
    where, line = enrolled
    key = where / w.KEY_NAME
    assert "PRIVATE KEY" in key.read_text()
    if os.name != "nt":
        assert stat.S_IMODE(key.stat().st_mode) == 0o600
    assert w.main(["--pubkey"]) == 0
    out = capsys.readouterr()
    assert out.out.strip() == line and "PRIVATE" not in out.out + out.err
    assert w.main(["--node", "pi5b", "--pubkey"]) == 0
    assert capsys.readouterr().out.startswith('"pi5b": "MCowBQYDK2VwAyEA')


@needs_openssl
def test_init_refuses_to_replace_a_key_without_force(enrolled, capsys):
    where, line = enrolled
    before = (where / w.KEY_NAME).read_bytes()
    assert w.main(["--init"]) == 1
    assert "already has a witness key" in capsys.readouterr().err
    assert (where / w.KEY_NAME).read_bytes() == before
    assert w.main(["--init", "--force"]) == 0
    assert capsys.readouterr().out.strip() != line
    assert (where / w.KEY_NAME).read_bytes() != before


def test_no_key_means_not_enrolled_and_a_clean_exit(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WITNESS_DIR", str(tmp_path / "none"))
    assert w.main([]) == 0
    assert "not enrolled" in capsys.readouterr().out
    assert w.main(["--pubkey"]) == 1
    assert not (tmp_path / "none").exists()


def test_a_key_that_cannot_sign_is_said_and_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WITNESS_DIR", str(tmp_path))
    monkeypatch.setenv("OPENSSL", "no-such-openssl-here")
    (tmp_path / w.KEY_NAME).write_text("not a key")
    assert w.main(["--seconds", "0"]) == 1
    assert "openssl is not installed" in capsys.readouterr().err


def test_node_and_bus_come_from_the_repo_env_file_when_run_by_hand(tmp_path, monkeypatch):
    monkeypatch.delenv("RADIO_NODE", raising=False)
    env = tmp_path / ".env"
    env.write_text("SENSING_SSID=x\nRADIO_NODE='pi5b'\nBUS_HOST=\n")
    assert w.env_value("RADIO_NODE", "pi5", env) == "pi5b"
    assert w.env_value("BUS_HOST", "192.168.77.2", env) == "192.168.77.2"
    monkeypatch.setenv("RADIO_NODE", "pi5")
    assert w.env_value("RADIO_NODE", "x", env) == "pi5"


# --- a bus that comes and goes ----------------------------------------------------------------

class FakeBus:
    """A UDP socket on the bus's side: collects what the witness sends, sends heads to whoever asked."""

    def __init__(self, port=0):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", port))
        self.sock.settimeout(0.05)
        self.port = self.sock.getsockname()[1]
        self.asker = None

    def wait(self, type_, seconds=5.0):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                data, addr = self.sock.recvfrom(4096)
            except (socket.timeout, ConnectionResetError):
                continue
            msg = json.loads(data)
            if msg["type"] == "chain_sub":
                self.asker = addr
            if msg["type"] == type_:
                return msg
        raise AssertionError(f"no {type_} within {seconds} s")

    def send(self, data):
        self.sock.sendto(data, self.asker)

    def close(self):
        self.sock.close()


@pytest.fixture
def running(wit):
    bus = FakeBus()
    stop = threading.Event()
    thread = threading.Thread(target=w.run, args=(wit, ("127.0.0.1", bus.port)),
                              kwargs=dict(stop=stop, sub_every=0.1, status_every=0.2), daemon=True)
    thread.start()
    yield wit, bus
    stop.set()
    thread.join(5)
    assert not thread.is_alive()
    bus.close()


def test_asks_the_bus_then_answers_each_head(running):
    wit, bus = running
    sub = bus.wait("chain_sub")
    assert sub["v"] == 2 and sub["node"] == "pi5" and sub["t"] > 0
    bus.send(b"junk")
    bus.send(head(0))
    bus.send(head(41, H1))
    assert bus.wait("chain_witness")["seq"] == 41
    bus.send(head(42, H2))
    assert bus.wait("chain_witness")["hash"] == H2
    assert wit.ignored == 2 and [e["seq"] for e in lines(wit)] == [41, 42]
    time.sleep(0.5)                       # status_every is 0.2 s here
    assert any("last seq signed 42, 2 signatures a minute" in line for line in wit.said)


def test_a_head_from_somewhere_else_is_not_signed(running):
    wit, bus = running
    bus.wait("chain_sub")
    other = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    other.bind(("127.0.0.2", 0))
    other.sendto(head(99, H3), bus.asker)
    other.close()
    bus.send(head(41, H1))
    assert bus.wait("chain_witness")["seq"] == 41
    assert [e["seq"] for e in lines(wit)] == [41]


def test_survives_the_bus_dropping_and_carries_on_when_it_is_back(running):
    wit, bus = running
    bus.wait("chain_sub")
    bus.send(head(41, H1))
    assert bus.wait("chain_witness")["seq"] == 41
    port = bus.port
    bus.close()
    time.sleep(0.5)                       # asks go nowhere; the witness keeps running
    back = FakeBus(port)
    try:
        back.wait("chain_sub")            # it asks again by itself
        back.send(head(42, H2))
        assert back.wait("chain_witness")["seq"] == 42
    finally:
        back.close()
