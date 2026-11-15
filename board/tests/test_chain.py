"""The board's side of the sealed record: the three endpoints, the 30 s check, the head on the bus and
the witnesses' signatures (CONTRACTS.md section 13)."""
import base64
import json
import shutil
import socket
import subprocess
import threading
import urllib.error
import urllib.request

import pytest

from board import chain, serve
from contracts import check
from store import Store
from store.chain import ZERO, canon

T0 = 1_763_149_500_000
OPENSSL = shutil.which("openssl")
needs_openssl = pytest.mark.skipif(OPENSSL is None, reason="no openssl on this machine")
# A public key file as openssl writes it. The key bytes are made up: nothing here is a real device's key.
PEM = "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAAAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=\n-----END PUBLIC KEY-----\n"
SIG = base64.b64encode(bytes(range(64))).decode()


def state(t):
    return {"v": 2, "type": "state", "t": t, "seq": 1, "src": "live", "cam": "off", "router": "S-home", "links": [],
            "health": {"status": "ok", "blind": [], "reason": None},
            "pred": {"present": True, "kind": "person", "zone": 1, "motion": "still", "still_s": 2.0},
            "alert": {"state": "none", "zone": None, "still_s": 0, "limit_s": None}, "advice": None, "model": None}


class Clock:
    """The board's clock (ms, can be stepped) and a clock that never steps (s)."""

    def __init__(self):
        self.ms, self.s = T0 + 60_000, 100.0

    def go(self, seconds):
        self.ms += int(seconds * 1000)
        self.s += seconds


@pytest.fixture
def clock():
    return Clock()


def keeper(tmp_path, clock, nodes=("pi5", "pi5b"), verify=lambda pem, message, sig: True, seconds=5, **kw):
    store = Store(tmp_path / "store.db")
    for i in range(seconds):
        store.add(state(T0 + i * 1000))
    keys = tmp_path / "witness_keys.local.json"
    if nodes is not None:
        keys.write_text(json.dumps({node: PEM for node in nodes}), encoding="utf-8")
    logged = []
    k = chain.Keeper(store, keys, clock=lambda: clock.ms, mono=lambda: clock.s, verify=verify, log=logged.append, **kw)
    k.logged = logged
    return k


def witness(k, node="pi5", sig=SIG, **over):
    head = k.store.head()
    return {"v": 2, "type": "chain_witness", "t": T0 + 61_000, "seq": head["seq"], "src": "live", "node": node,
            "hash": head["hash"], "sig": sig, **over}


def kinds(k):
    return [(r["kind"], r["body"].get("node")) for r in k.store.records() if r["kind"] != "second"]


# ---- openssl ----

def test_the_signed_bytes_are_node_seq_hash_t_with_bars_and_no_newline():
    assert chain.signed_bytes("pi5", 4127, "ab" * 32, 1763149515000) == b"pi5|4127|" + b"ab" * 32 + b"|1763149515000"


def test_the_openssl_call_is_the_one_in_the_contract():
    assert chain.verify_command("openssl", "witness.pub", "msg.bin", "sig.bin") == \
        "openssl pkeyutl -verify -pubin -inkey witness.pub -rawin -in msg.bin -sigfile sig.bin".split()


@pytest.fixture(scope="module")
def device(tmp_path_factory):
    """A key pair made the way a witness makes its own at install, in a folder that is thrown away."""
    folder = tmp_path_factory.mktemp("device")
    key = folder / "witness.key"
    subprocess.run([OPENSSL, "genpkey", "-algorithm", "ed25519", "-out", str(key)], check=True, capture_output=True)
    pub = subprocess.run([OPENSSL, "pkey", "-in", str(key), "-pubout"], check=True, capture_output=True).stdout.decode()

    def sign(message: bytes) -> bytes:
        (folder / "msg.bin").write_bytes(message)
        subprocess.run([OPENSSL, "pkeyutl", "-sign", "-inkey", str(key), "-rawin", "-in", str(folder / "msg.bin"),
                        "-out", str(folder / "sig.bin")], check=True, capture_output=True)
        return (folder / "sig.bin").read_bytes()
    return pub, sign


@needs_openssl
def test_real_openssl_takes_a_true_signature_and_refuses_anything_else(device):
    pub, sign = device
    message = chain.signed_bytes("pi5", 12, "9f" * 32, T0)
    sig = sign(message)
    assert len(sig) == 64
    assert chain.openssl_verify(pub, message, sig) is True
    assert chain.openssl_verify(pub, chain.signed_bytes("pi5", 13, "9f" * 32, T0), sig) is False    # another record
    assert chain.openssl_verify(pub, message, bytes(64)) is False
    assert chain.openssl_verify(PEM, message, sig) is False                                         # another key
    assert chain.openssl_verify(pub, message, sig, openssl="no-such-openssl") is None               # can't be run


@needs_openssl
def test_a_signature_made_on_a_device_is_stored_and_a_forged_one_is_not(tmp_path, clock, device):
    pub, sign = device
    k = keeper(tmp_path, clock, nodes=None, verify=chain.openssl_verify)
    k.keys_file.write_text(json.dumps({"pi5": pub, "pi5b": pub.splitlines()[1]}), encoding="utf-8")   # either way of enrolling
    k.reload_keys()
    head, t = k.store.head(), clock.ms
    sig = sign(chain.signed_bytes("pi5", head["seq"], head["hash"], t))
    good = witness(k, t=t, sig=base64.b64encode(sig).decode())
    assert check.errors(good) == [] and k.on_witness(good) == "witness"
    assert k.on_witness(witness(k, "pi5b", t=t, sig=sig.hex())) == "witness_bad"      # pi5's signature under pi5b's name
    stored = k.store.records(kinds=["witness", "witness_bad"])
    assert stored[0]["body"] == {"node": "pi5", "seq": head["seq"], "hash": head["hash"], "t": t,
                                 "sig": base64.b64encode(sig).decode()}
    assert stored[1]["body"]["why"] == "the signature does not match the enrolled key"
    assert all(check.errors(r, "record") == [] for r in stored) and k.store.verify()["ok"]


# ---- enrolment ----

def test_no_key_file_means_no_witnesses_and_is_not_an_error(tmp_path, clock):
    k = keeper(tmp_path, clock, nodes=None)
    assert chain.load_keys(tmp_path / "nothing.json") == {} and k.status()["witnesses"] == []
    assert k.on_witness(witness(k)) is None and k.dropped == 1
    clock.go(60)
    assert k.tick() == [] and kinds(k) == []
    assert k.head_message()["witnesses"] == 0


@pytest.mark.parametrize("text", ["not json", "[1, 2]", '{"pi5": 7, "pi5b": "not a key"}'])
def test_a_key_file_that_cant_be_used_enrols_nobody(tmp_path, text):
    path = tmp_path / "keys.json"
    path.write_text(text, encoding="utf-8")
    assert chain.load_keys(path) == {}


def test_a_key_is_taken_as_the_pem_text_or_as_its_base64_alone():
    middle = PEM.splitlines()[1]
    raw = base64.b64encode(base64.b64decode(middle)[12:]).decode()
    assert chain.to_pem(PEM) == chain.to_pem(middle) == chain.to_pem(raw) == chain.to_pem("  " + PEM.replace("\n", "\r\n")) == PEM
    assert chain.to_pem("-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----") is None
    assert chain.to_pem(base64.b64encode(bytes(31)).decode()) is None


def test_a_key_enrolled_while_running_is_picked_up(tmp_path, clock):
    k = keeper(tmp_path, clock, nodes=("pi5",))
    assert [w["node"] for w in k.status()["witnesses"]] == ["pi5"]
    k.keys_file.write_text(json.dumps({"pi5": PEM, "pi5b": PEM}), encoding="utf-8")
    k.reload_keys()
    assert [w["node"] for w in k.status()["witnesses"]] == ["pi5", "pi5b"]
    assert k.logged[-1] == "witnesses enrolled: pi5, pi5b"


# ---- the witnesses ----

def test_a_good_signature_is_stored_as_a_witness_record_and_reported(tmp_path, clock):
    k = keeper(tmp_path, clock)
    assert k.status()["witnesses"][0] == {"node": "pi5", "last_seq": None, "last_t": None, "sig_ok": False, "silent": False}
    assert k.on_witness(witness(k)) == "witness"
    assert k.status()["witnesses"] == [
        {"node": "pi5", "last_seq": 5, "last_t": clock.ms, "sig_ok": True, "silent": False},
        {"node": "pi5b", "last_seq": None, "last_t": None, "sig_ok": False, "silent": False}]
    record = k.store.records(6, 6)[0]
    assert record["kind"] == "witness" and record["t"] == clock.ms and record["body"]["seq"] == 5
    assert k.counts() == (1, 2) and k.store.verify()["ok"]
    assert check.errors(k.status(), "chain") == []


def test_the_same_head_signed_twice_is_stored_once_and_still_counts_as_alive(tmp_path, clock):
    k = keeper(tmp_path, clock)
    first = witness(k)
    assert [k.on_witness(first), k.on_witness(first)] == ["witness", "again"]
    assert kinds(k) == [("witness", "pi5")]
    clock.go(14)
    assert k.on_witness(first) == "again"
    clock.go(14)
    assert k.tick() == ["pi5b"]                       # pi5 signed 14 s ago: only the other one is silent


@pytest.mark.parametrize("change, why", [
    ({"sig": "AAAA"}, "the signature is not 64 bytes in base64 or hex"),
    ({"hash": "ab" * 32}, "the board holds no record with that number and hash"),
    ({"seq": 99}, "the board holds no record with that number and hash"),
    ({"seq": "5"}, "the message does not name a head (seq, hash, t)"),
    ({"t": None}, "the message does not name a head (seq, hash, t)"),
])
def test_a_message_that_cant_be_a_signature_of_a_head_is_stored_as_bad(tmp_path, clock, change, why):
    k = keeper(tmp_path, clock)
    assert k.on_witness(witness(k, **change)) == "witness_bad"
    bad = k.store.records(kinds=["witness_bad"])[0]
    assert bad["body"]["node"] == "pi5" and bad["body"]["why"] == why and check.errors(bad, "record") == []
    assert k.status()["witnesses"][0]["sig_ok"] is False


def test_a_signature_that_does_not_check_out_is_stored_as_bad_at_most_once_in_5_s(tmp_path, clock):
    k = keeper(tmp_path, clock, verify=lambda pem, message, sig: False)
    assert [k.on_witness(witness(k)) for _ in range(3)] == ["witness_bad", None, None]
    clock.go(5)
    assert k.on_witness(witness(k)) == "witness_bad"
    assert kinds(k) == [("witness_bad", "pi5"), ("witness_bad", "pi5")] and k.counts() == (0, 2)


def test_openssl_missing_on_the_board_is_said_in_the_record(tmp_path, clock):
    k = keeper(tmp_path, clock, verify=lambda pem, message, sig: None)
    assert k.on_witness(witness(k)) == "witness_bad"
    assert k.store.records(kinds=["witness_bad"])[0]["body"]["why"] == "openssl could not be run on the board"


def test_a_node_that_is_not_enrolled_is_dropped_and_nothing_is_stored(tmp_path, clock):
    k = keeper(tmp_path, clock, nodes=("pi5",))
    assert k.on_witness(witness(k, "pi5b")) is None and k.on_witness(witness(k, node=None)) is None
    assert k.on_witness("not a message") is None
    assert kinds(k) == [] and k.dropped == 3


def test_the_check_gets_the_key_the_bytes_and_the_signature(tmp_path, clock):
    seen = []
    k = keeper(tmp_path, clock, verify=lambda pem, message, sig: seen.append((pem, message, sig)) or True)
    k.on_witness(witness(k, t=T0 + 7))
    head = k.store.records(5, 5)[0]
    assert seen == [(PEM, f"pi5|5|{head['hash']}|{T0 + 7}".encode(), bytes(range(64)))]


def test_a_silent_witness_is_stored_once_and_once_more_when_it_is_back(tmp_path, clock):
    k = keeper(tmp_path, clock)
    k.on_witness(witness(k, "pi5"))
    k.on_witness(witness(k, "pi5b"))
    for _ in range(6):                              # pi5 keeps signing; pi5b stops
        clock.go(5)
        k.on_witness(witness(k, "pi5"))
        k.tick()
    assert kinds(k).count(("witness_silent", "pi5b")) == 1 and ("witness_silent", "pi5") not in kinds(k)
    silent = k.status()["witnesses"][1]
    assert silent["silent"] is True and silent["sig_ok"] is True and silent["last_seq"] == 6
    assert k.counts() == (1, 2)
    clock.go(5)
    assert k.on_witness(witness(k, "pi5b")) == "witness"
    assert kinds(k)[-2:] == [("witness", "pi5b"), ("witness_back", "pi5b")]
    assert k.status()["witnesses"][1]["silent"] is False and k.counts() == (2, 2)
    clock.go(5)
    k.on_witness(witness(k, "pi5b"))
    assert kinds(k).count(("witness_back", "pi5b")) == 1
    assert k.store.verify()["ok"]                   # the chain went on through all of it


def test_a_witness_that_never_signs_is_silent_15_s_after_the_start(tmp_path, clock):
    k = keeper(tmp_path, clock)
    clock.go(14)
    assert k.tick() == []
    clock.go(1)
    assert k.tick() == ["pi5", "pi5b"] and k.tick() == []
    assert kinds(k) == [("witness_silent", "pi5"), ("witness_silent", "pi5b")]


def test_setting_the_boards_clock_makes_no_witness_silent(tmp_path, clock):
    k = keeper(tmp_path, clock)
    k.on_witness(witness(k))
    k.on_witness(witness(k, "pi5b"))
    clock.ms += 520_000                             # the operator sets the clock: nearly nine minutes forward
    clock.go(2)
    assert k.tick() == []
    clock.ms -= 1_040_000                           # and back again
    assert k.tick() == [] and all(not w["silent"] for w in k.status()["witnesses"])


def test_a_restarted_web_server_does_not_store_the_same_silence_twice(tmp_path, clock):
    k = keeper(tmp_path, clock)
    clock.go(15)
    k.tick()
    again = chain.Keeper(k.store, k.keys_file, clock=lambda: clock.ms, mono=lambda: clock.s, log=lambda text: None)
    assert all(w["silent"] for w in again.status()["witnesses"])
    clock.go(30)
    assert again.tick() == [] and len(kinds(k)) == 2


# ---- the check, the head, GET /chain ----

def test_the_check_says_checking_then_verified_then_names_an_edited_record(tmp_path, clock):
    k = keeper(tmp_path, clock, seconds=30)
    first = k.status()
    assert (first["verified"], first["last_verify_t"], first["first_bad_seq"]) == ("checking", None, None)
    assert (first["last_verify_checked"], first["last_verify_ms"]) == (None, None)       # nothing was checked yet
    assert "verified" not in k.head_message() and check.errors(first, "chain") == []
    assert k.verify_now()["checked"] == 30
    assert (k.status()["verified"], k.status()["last_verify_t"]) == (True, clock.ms) and k.head_message()["verified"] is True
    body = json.loads(k.store.db.execute("select body from chain where seq = 17").fetchone()[0])
    with k.store.db:
        k.store.db.execute("update chain set body = ? where seq = 17", (canon({**body, "present": 0}),))
    k.verify_now()
    bad = k.status()
    assert (bad["verified"], bad["first_bad_seq"]) == (False, 17) and check.errors(bad, "chain") == []
    assert k.head_message()["verified"] is False and "first bad record 17" in k.logged[-1]


def test_the_check_covers_the_last_10_minutes(tmp_path, clock):
    k = keeper(tmp_path, clock, seconds=0)
    for i in range(0, 1200, 10):                    # twenty minutes, a record every 10 s
        k.store.add(state(T0 + i * 1000))
    clock.ms = T0 + 1190 * 1000
    result = k.verify_now()
    assert result["ok"] and (result["from"], result["to"], result["checked"]) == (60, 120, 61)


def test_get_chain_says_what_the_log_holds(tmp_path, clock):
    k = keeper(tmp_path, clock, seconds=4)
    k.verify_now()
    status = k.status()
    head = k.store.records(4, 4)[0]
    assert status == {"head": {"seq": 4, "hash": head["hash"]}, "records": 4, "since_t": T0, "verified": True,
                      "last_verify_t": clock.ms, "first_bad_seq": None,
                      "witnesses": [{"node": n, "last_seq": None, "last_t": None, "sig_ok": False, "silent": False}
                                    for n in ("pi5", "pi5b")],
                      "first_seq": 1, "anchor": None, "unsealed": 0,
                      "last_verify_checked": 4, "last_verify_ms": status["last_verify_ms"]}
    assert status["last_verify_ms"] >= 0 and check.errors(status, "chain") == []
    sent = k.publish()
    assert k.status()["head"] == {"seq": 4, "hash": head["hash"], "t": sent["t"]}      # what a witness can sign
    k.store.add(state(T0 + 9000))
    assert "t" not in k.status()["head"]            # a head that has not been sent yet carries no t


def test_an_empty_store_still_answers(tmp_path, clock):
    k = keeper(tmp_path, clock, seconds=0, nodes=None)
    k.verify_now()
    status = k.status()
    assert status["head"] == {"seq": 0, "hash": ZERO} and status["records"] == 0 and status["since_t"] is None
    assert status["verified"] is True and check.errors(status, "chain") == []
    assert check.errors(k.head_message()) == []


def test_the_head_goes_to_the_bus_as_the_contract_words_it(tmp_path, clock):
    sent = []
    k = keeper(tmp_path, clock, send=sent.append)
    k.on_witness(witness(k))
    k.verify_now()
    msg = k.publish()
    head = k.store.head()
    assert json.loads(sent[0]) == msg == {"v": 2, "type": "chain_head", "t": clock.ms, "seq": head["seq"], "src": "live",
                                          "hash": head["hash"], "witnesses_ok": 1, "witnesses": 2, "verified": True}
    assert check.errors(msg) == []


def test_a_bus_that_cant_be_reached_does_not_stop_the_keeper(tmp_path, clock):
    def unreachable(data):
        raise OSError("network is unreachable")
    k = keeper(tmp_path, clock, send=unreachable)
    assert k.publish()["type"] == "chain_head" and "could not reach the bus" in k.logged[-1]


def test_the_loop_checks_publishes_and_marks_silence_and_survives_a_bad_tick(tmp_path, clock):
    sent, stop = [], threading.Event()
    k = keeper(tmp_path, clock, send=sent.append)
    calls = iter([RuntimeError("the file is busy")])

    def reload():
        for error in calls:
            raise error
    k.reload_keys = reload
    real_wait = stop.wait

    def wait(seconds):
        clock.go(seconds)
        if clock.s >= 100 + 31:
            stop.set()
        return real_wait(0)
    stop.wait = wait
    k.run(stop, every_s=1.0)
    assert any("a tick failed" in line for line in k.logged)
    assert [json.loads(m)["type"] for m in sent] == ["chain_head"] * 6            # 30 s after the failed tick: one every 5 s
    assert k.status()["verified"] is True
    assert kinds(k) == [("witness_silent", "pi5"), ("witness_silent", "pi5b")]


def test_signatures_arrive_over_udp_from_the_bus(tmp_path, clock):
    k = keeper(tmp_path, clock)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    stop = threading.Event()
    thread = threading.Thread(target=k.listen, args=(sock, stop), daemon=True)
    thread.start()
    out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        out.sendto(b"not json", sock.getsockname())
        out.sendto(json.dumps({"v": 2, "type": "rssi"}).encode(), sock.getsockname())
        out.sendto(json.dumps(witness(k)).encode(), sock.getsockname())
        for _ in range(200):
            if kinds(k):
                break
            stop.wait(0.01)
    finally:
        stop.set()
        thread.join(2)
        out.close()
        sock.close()
    assert kinds(k) == [("witness", "pi5")]


# ---- over HTTP ----

@pytest.fixture
def web(tmp_path, clock):
    k = keeper(tmp_path, clock, seconds=40)
    (tmp_path / "dist").mkdir()
    (tmp_path / "nodes.json").write_text("{}")
    server = serve.make_server("127.0.0.1", 0, dist=tmp_path / "dist", nodes=tmp_path / "nodes.json",
                               proof=tmp_path / "proof.json", layout_path=tmp_path / "layout.json",
                               routes=chain.routes(k))
    threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", k, server
    server.shutdown()
    server.server_close()


def call(url, method="GET", body=None):
    req = urllib.request.Request(url, data=body, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_get_chain_over_http(web):
    url, k, _ = web
    status, doc = call(f"{url}/chain")
    assert status == 200 and doc == k.status() and check.errors(doc, "chain") == []
    assert doc["records"] == 40 and doc["verified"] == "checking"
    k.store.add(state(T0 + 99_000))
    assert call(f"{url}/chain")[1]["head"]["seq"] == 41            # the count rises as records are saved


def test_verify_over_http_takes_record_numbers(web):
    url, k, _ = web
    status, doc = call(f"{url}/chain/verify")
    assert status == 200 and (doc["ok"], doc["checked"], doc["first_bad_seq"], doc["from"], doc["to"]) == (True, 40, None, 1, 40)
    assert check.errors(doc, "chain_verify") == []
    assert call(f"{url}/chain/verify?from=10&to=19")[1]["checked"] == 10
    assert call(f"{url}/chain/verify?from=30")[1]["checked"] == 11
    assert call(f"{url}/chain/verify?to=5")[1]["checked"] == 5
    with k.store.db:
        k.store.db.execute("update chain set t = t + 1 where seq = 22")
    status, doc = call(f"{url}/chain/verify?from=1&to=40")
    assert status == 200 and (doc["ok"], doc["first_bad_seq"]) == (False, 22) and check.errors(doc, "chain_verify") == []


@pytest.mark.parametrize("query, word", [("from=abc", "from must be a record number"), ("to=0", "to must be a record number"),
                                         ("from=9&to=3", "to is before from"), ("from=1&from=2", "more than once")])
def test_verify_refuses_a_range_it_cant_read(web, query, word):
    status, doc = call(f"{web[0]}/chain/verify?{query}")
    assert status == 400 and word in doc["error"]


def test_prove_alters_a_copy_names_the_record_and_leaves_the_log_alone(web):
    url, k, _ = web
    before = [tuple(r) for r in k.store.db.execute("select * from chain order by seq")]
    status, doc = call(f"{url}/chain/prove", "POST", b"{}")
    assert status == 200 and check.errors(doc, "chain_prove") == []
    assert (doc["ok"], doc["altered_seq"], doc["first_bad_seq"], doc["checked"]) == (False, 21, 21, 40)
    status, doc = call(f"{url}/chain/prove", "POST", b'{"n": 10, "seq": 35}')
    assert status == 200 and (doc["altered_seq"], doc["first_bad_seq"], doc["kind"]) == (35, 35, "second")
    assert call(f"{url}/chain/prove", "POST", b"")[0] == 200       # no body is the same as {}
    assert [tuple(r) for r in k.store.db.execute("select * from chain order by seq")] == before
    assert call(f"{url}/chain/verify")[1]["ok"] is True            # the real log still verifies


@pytest.mark.parametrize("body, status", [(b'{"n": 0}', 400), (b'{"seq": "x"}', 400), (b"[1]", 400), (b"not json", 400),
                                          (b'{"n": 5, "seq": 2}', 400)])
def test_prove_refuses_a_bad_request(web, body, status):
    assert call(f"{web[0]}/chain/prove", "POST", body)[0] == status


def test_prove_with_no_record_yet_says_so(tmp_path, clock):
    k = keeper(tmp_path, clock, seconds=0)
    with pytest.raises(serve.ApiError) as e:
        chain.routes(k)[("POST", "/chain/prove")](serve.Request({}, b"{}", "127.0.0.1"))
    assert e.value.status == 409 and "no sealed record yet" in e.value.message


def test_the_chain_endpoints_answer_only_on_the_boards_own_networks(web, monkeypatch):
    url, _, _ = web
    monkeypatch.setattr(serve, "SAVE_FROM", [])                    # as if the caller were anywhere else
    for method, path in (("GET", "/chain"), ("GET", "/chain/verify"), ("GET", "/chain/tail"), ("POST", "/chain/prove")):
        status, doc = call(url + path, method, b"{}" if method == "POST" else None)
        assert status == 403 and "own networks" in doc["error"]


def test_the_web_server_mounts_the_chain_and_starts_its_loops(tmp_path, monkeypatch):
    started = {}

    def start(store, keys, bus, listen):
        started.update(store=store, keys=keys, bus=bus, listen=listen)
        return chain.Keeper(store, tmp_path / "none.json", log=lambda text: None), threading.Event()
    monkeypatch.setattr(chain, "start", start)
    routes = serve.chain_routes(tmp_path / "store.db", "keys.json", ("127.0.0.1", 5999), 0)
    assert sorted(routes) == [("GET", "/chain"), ("GET", "/chain/tail"), ("GET", "/chain/verify"), ("POST", "/chain/prove")]
    assert (started["keys"], started["bus"], started["listen"]) == ("keys.json", ("127.0.0.1", 5999), None)
    serve.chain_routes(tmp_path / "store.db")
    assert (started["bus"], started["listen"]) == (chain.BUS, chain.LISTEN)


def test_the_tail_is_the_last_records_and_says_what_each_signature_vouches_for(web):
    url, k, _ = web
    k.on_witness(witness(k, "pi5"))                       # signs record 40: stored as record 41
    clock_s = k.mono()
    k.mono = lambda: clock_s + 20
    k.tick()                                              # 20 s on with no signature: both are stored as silent
    status, doc = call(f"{url}/chain/tail?n=5")
    assert status == 200 and check.errors(doc, "chain_tail") == []
    rows = doc["records"]
    assert [(r["seq"], r["kind"]) for r in rows] == [(39, "second"), (40, "second"), (41, "witness"), (42, "witness_silent"), (43, "witness_silent")]
    assert (rows[2]["node"], rows[2]["for_seq"]) == ("pi5", 40) and rows[2]["prev"] == rows[1]["hash"]
    assert rows[4]["node"] == "pi5b" and "for_seq" not in rows[4] and "node" not in rows[0]
    assert set(rows[0]) == {"seq", "t", "kind", "hash", "prev"}          # never the body
    assert len(call(f"{url}/chain/tail")[1]["records"]) == 40            # 40 unless n says otherwise
    assert len(call(f"{url}/chain/tail?n=100000")[1]["records"]) == 43   # capped (at 200), and no more than there is
    assert k.store.tail(500)[0]["seq"] == 1
    for bad in ("n=0", "n=abc", "n=-3"):
        assert call(f"{url}/chain/tail?{bad}")[0] == 400


def test_the_tail_is_capped_at_200_and_empty_with_no_record(tmp_path, clock):
    k = keeper(tmp_path, clock, seconds=230)
    assert [r["seq"] for r in k.store.tail(5000)] == list(range(31, 231))
    assert Store(tmp_path / "empty.db").tail() == []
