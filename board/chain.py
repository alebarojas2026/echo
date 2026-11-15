"""The board's side of the sealed record and its witnesses (CONTRACTS.md section 13).

Runs inside the web server (board/serve.py), next to the store's file:

- GET /chain, GET /chain/verify?from=&to=, GET /chain/tail?n= and POST /chain/prove, mounted like /history;
- every 30 s, a check of the last 10 minutes of the chain (what /chain reports as verified);
- every 5 s, the chain head on the bus (chain_head), which the bus passes on to the witnesses and
  the brain copies into state.chain;
- each chain_witness the bus passes on (UDP 127.0.0.1:5602): the Ed25519 signature over the bytes
  node|seq|hash|t is checked against that node's enrolled public key with the device's openssl,
  and stored in the chain as a witness record (witness_bad when it does not check out);
- a witness with no good signature for 15 s is stored once as witness_silent, and once as
  witness_back when it signs again. The chain goes on either way.

Public keys are enrolled in a local file that is never in git, data/witness_keys.local.json (or
WITNESS_KEYS): {"pi5": "<PEM text of the public key>", "pi5b": "..."}. No file means no witnesses
are enrolled; that is not an error. The file is read again on every tick, so a key can be enrolled
without a restart. Private keys never leave the devices that made them.

Standard library only; openssl is called as a program.
"""
import base64
import binascii
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http import HTTPStatus
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KEYS = REPO / "data" / "witness_keys.local.json"
BUS = ("127.0.0.1", 5600)
LISTEN = ("127.0.0.1", 5602)     # where the bus passes chain_witness on
HEAD_EVERY_S = 5.0
VERIFY_EVERY_S = 30.0
VERIFY_SPAN_MS = 10 * 60 * 1000
SILENT_AFTER_S = 15.0
BAD_EVERY_S = 5.0                # at most one witness_bad per node in this long
HEX64 = re.compile(r"^[0-9a-f]{64}$")
PEM = re.compile(r"-----BEGIN PUBLIC KEY-----\s+([A-Za-z0-9+/=\s]+)-----END PUBLIC KEY-----")
ED25519_DER = bytes.fromhex("302a300506032b6570032100")   # what comes before the 32 key bytes in a public key file


def now_ms() -> int:
    return int(time.time() * 1000)


def keys_path() -> Path:
    return Path(os.environ.get("WITNESS_KEYS") or KEYS)


def to_pem(value):
    """An enrolled key as PEM text, or None when it is not one. Taken: the PEM text openssl prints,
    or the key alone in base64 (the middle line of that text, or the 32 raw bytes)."""
    if not isinstance(value, str):
        return None
    found = PEM.search(value)
    if found:
        value = "".join(found.group(1).split())
    try:
        raw = base64.b64decode(value.strip(), validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(raw) == 32:
        raw = ED25519_DER + raw
    if len(raw) != 44 or not raw.startswith(ED25519_DER):
        return None
    return f"-----BEGIN PUBLIC KEY-----\n{base64.b64encode(raw).decode()}\n-----END PUBLIC KEY-----\n"


def load_keys(path) -> dict:
    """{node: PEM text} from the enrolment file. {} when there is no file, or it can't be read: no
    witnesses are enrolled. An entry that is not a public key is left out."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(doc, dict):
        return {}
    keys = {node: to_pem(value) for node, value in doc.items() if isinstance(node, str)}
    return {node: pem for node, pem in keys.items() if pem}


def signed_bytes(node: str, seq: int, digest: str, t: int) -> bytes:
    """What a witness signs: node|seq|hash|t, no newline."""
    return f"{node}|{seq}|{digest}|{t}".encode("ascii")


def sig_bytes(text):
    """The 64 signature bytes from base64 or hex, or None."""
    if not isinstance(text, str):
        return None
    text = text.strip()
    try:
        raw = bytes.fromhex(text) if len(text) == 128 else base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        return None
    return raw if len(raw) == 64 else None


def verify_command(openssl: str, pub: str, message: str, sig: str) -> list:
    """The one openssl call that checks an Ed25519 signature (OpenSSL 3). Ed25519 signs the message
    itself, not a digest of it, so -rawin; and it needs the whole message at once, so the message
    and the signature are files, not stdin."""
    return [openssl, "pkeyutl", "-verify", "-pubin", "-inkey", pub, "-rawin", "-in", message, "-sigfile", sig]


def openssl_verify(pem: str, message: bytes, sig: bytes, openssl: str = "openssl", timeout_s: float = 5.0):
    """True when sig is pem's Ed25519 signature over message, False when it is not, None when
    openssl could not be run here (not installed, or it did not answer in time)."""
    program = shutil.which(openssl)
    if program is None:
        return None
    with tempfile.TemporaryDirectory(prefix="witness-") as folder:
        paths = {name: os.path.join(folder, name) for name in ("pub.pem", "msg.bin", "sig.bin")}
        for name, data in (("pub.pem", pem.encode("ascii")), ("msg.bin", message), ("sig.bin", sig)):
            with open(paths[name], "wb") as f:
                f.write(data)
        try:
            done = subprocess.run(verify_command(program, paths["pub.pem"], paths["msg.bin"], paths["sig.bin"]),
                                  capture_output=True, timeout=timeout_s)
        except (OSError, subprocess.TimeoutExpired):
            return None
    return done.returncode == 0


class Keeper:
    """The chain's state on the board: the last check, each witness, and what goes out as chain_head.

    store: a store.Store on the same file the store process writes. clock: epoch ms. mono: seconds
    that never step (silence is counted on it, so setting the board's clock makes no witness silent).
    verify: (pem, message, sig) -> True | False | None. send: bytes -> None, to the bus."""

    def __init__(self, store, keys=None, clock=now_ms, mono=time.monotonic, verify=openssl_verify, send=None,
                 log=None):
        self.store, self.keys_file = store, Path(keys) if keys else keys_path()
        self.clock, self.mono, self.check, self.send = clock, mono, verify, send or (lambda data: None)
        self.log = log or (lambda text: print(f"chain: {text}", file=sys.stderr, flush=True))
        self.lock = threading.Lock()
        self.verified, self.last_verify_t, self.first_bad_seq = "checking", None, None
        self.last_verify_checked = self.last_verify_ms = None    # how much the last check walked, and how long it took
        self.started = mono()
        self.witnesses = {}          # node -> {last_seq, last_t, sig_ok, silent, good_at, bad_at}
        self.sent = None             # the last chain_head sent: {"seq", "t"}
        self.dropped = 0             # messages from nodes that are not enrolled, or not readable
        self.keys = {}
        self.reload_keys()

    # ---- enrolment ----

    def reload_keys(self) -> None:
        keys = load_keys(self.keys_file)
        with self.lock:
            if set(keys) != set(self.keys):
                self.log(f"witnesses enrolled: {', '.join(sorted(keys)) or 'none'}")
            self.keys = keys
            for node in keys:
                if node not in self.witnesses:
                    self.witnesses[node] = {"last_seq": None, "last_t": None, "sig_ok": False, "good_at": None,
                                            "bad_at": None, "silent": self._was_silent(node)}
            for node in [n for n in self.witnesses if n not in keys]:
                del self.witnesses[node]

    def _was_silent(self, node: str) -> bool:
        """Whether the chain's last word on this witness is that it went silent (before a restart of
        the web server), so it is not stored a second time."""
        last = [r for r in self.store.records(kinds=["witness_silent", "witness_back", "witness"], limit=50, newest=True)
                if r["body"].get("node") == node]
        return bool(last) and last[-1]["kind"] == "witness_silent"

    # ---- the check every 30 s ----

    def verify_now(self) -> dict:
        result = self.store.verify_since(self.clock() - VERIFY_SPAN_MS)
        with self.lock:
            if not result["ok"] and self.verified is not False:
                self.log(f"the chain does NOT verify: first bad record {result['first_bad_seq']}")
            self.verified, self.first_bad_seq, self.last_verify_t = result["ok"], result["first_bad_seq"], self.clock()
            self.last_verify_checked, self.last_verify_ms = result["checked"], result["ms"]
        return result

    # ---- the head every 5 s ----

    def counts(self) -> tuple:
        """(witnesses signing, witnesses enrolled)."""
        with self.lock:
            return sum(1 for w in self.witnesses.values() if w["sig_ok"] and not w["silent"]), len(self.witnesses)

    def head_message(self) -> dict:
        head, (signing, enrolled) = self.store.head(), self.counts()
        msg = {"v": 2, "type": "chain_head", "t": self.clock(), "seq": head["seq"], "src": "live", "hash": head["hash"],
               "witnesses_ok": signing, "witnesses": enrolled}
        if self.verified in (True, False):
            msg["verified"] = self.verified
        return msg

    def publish(self) -> dict:
        msg = self.head_message()
        with self.lock:
            self.sent = {"seq": msg["seq"], "t": msg["t"]}
        try:
            self.send(json.dumps(msg, separators=(",", ":")).encode())
        except OSError as e:
            self.log(f"could not reach the bus: {e}")
        return msg

    # ---- the witnesses ----

    def on_witness(self, msg: dict):
        """One chain_witness. Returns the kind stored ("witness", "witness_bad"), "again" for a head
        this witness has signed before, or None when the message was dropped."""
        node = msg.get("node") if isinstance(msg, dict) else None
        with self.lock:
            pem, witness = self.keys.get(node), self.witnesses.get(node)
        if pem is None or witness is None:
            self.dropped += 1
            return None
        seq, digest, t = msg.get("seq"), msg.get("hash"), msg.get("t")
        sig, why = sig_bytes(msg.get("sig")), None
        if not (type(seq) is int and type(t) is int and isinstance(digest, str) and HEX64.match(digest)):
            why = "the message does not name a head (seq, hash, t)"
        elif sig is None:
            why = "the signature is not 64 bytes in base64 or hex"
        else:
            held = self.store.records(seq, seq)
            if not held or held[0]["hash"] != digest:
                why = "the board holds no record with that number and hash"
            else:
                checked = self.check(pem, signed_bytes(node, seq, digest, t), sig)
                if checked is None:
                    why = "openssl could not be run on the board"
                elif not checked:
                    why = "the signature does not match the enrolled key"
        now, mono = self.clock(), self.mono()
        if why is not None:
            with self.lock:
                witness["sig_ok"] = False
                quiet = witness["bad_at"] is not None and mono - witness["bad_at"] < BAD_EVERY_S
                witness["bad_at"] = mono if not quiet else witness["bad_at"]
            if quiet:
                return None
            self.store.append("witness_bad", {"node": node, "seq": seq if type(seq) is int else None, "why": why}, now)
            return "witness_bad"
        with self.lock:
            again = witness["last_seq"] is not None and seq <= witness["last_seq"]
            back, witness["silent"] = witness["silent"], False
            witness.update(sig_ok=True, good_at=mono, last_t=now, last_seq=max(seq, witness["last_seq"] or 0))
        if not again:
            self.store.append("witness", {"node": node, "seq": seq, "hash": digest, "t": t,
                                          "sig": base64.b64encode(sig).decode()}, now)
        if back:
            self.store.append("witness_back", {"node": node}, now)
        return "again" if again else "witness"

    def tick(self) -> list:
        """The 15 s rule. Returns the nodes stored as silent just now."""
        mono, gone = self.mono(), []
        with self.lock:
            for node, w in self.witnesses.items():
                since = w["good_at"] if w["good_at"] is not None else self.started
                if not w["silent"] and mono - since >= SILENT_AFTER_S:
                    w["silent"] = True
                    gone.append(node)
        for node in gone:
            self.store.append("witness_silent", {"node": node}, self.clock())
        return gone

    # ---- GET /chain ----

    def status(self) -> dict:
        info = self.store.chain_info()
        with self.lock:
            if self.sent and self.sent["seq"] == info["head"]["seq"]:
                info["head"]["t"] = self.sent["t"]
            witnesses = [{"node": node, "last_seq": w["last_seq"], "last_t": w["last_t"], "sig_ok": w["sig_ok"],
                          "silent": w["silent"]} for node, w in sorted(self.witnesses.items())]
            return {"head": info["head"], "records": info["records"], "since_t": info["since_t"],
                    "verified": self.verified, "last_verify_t": self.last_verify_t,
                    "first_bad_seq": self.first_bad_seq if self.verified is False else None,
                    "witnesses": witnesses, "first_seq": info["first_seq"], "anchor": info["anchor"],
                    "unsealed": info["unsealed"], "last_verify_checked": self.last_verify_checked,
                    "last_verify_ms": self.last_verify_ms}

    # ---- the two loops ----

    def run(self, stop: threading.Event, every_s: float = 1.0) -> None:
        """Tick until stop is set: the silence rule each second, the head every 5 s, the check every 30 s.
        Nothing here may end the loop: a store that can't be read right now is tried again."""
        next_head = next_verify = self.mono()
        while not stop.is_set():
            try:
                self.reload_keys()
                self.tick()
                if self.mono() >= next_verify:
                    next_verify = self.mono() + VERIFY_EVERY_S
                    self.verify_now()
                if self.mono() >= next_head:
                    next_head = self.mono() + HEAD_EVERY_S
                    self.publish()
            except Exception as e:
                self.log(f"a tick failed ({e!r}); trying again")
            stop.wait(every_s)

    def listen(self, sock: socket.socket, stop: threading.Event) -> None:
        """Take chain_witness messages from the bus until stop is set."""
        sock.settimeout(0.25)
        while not stop.is_set():
            try:
                data, _ = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                continue   # Windows reports an earlier unreachable send this way
            try:
                msg = json.loads(data)
                if isinstance(msg, dict) and msg.get("v") == 2 and msg.get("type") == "chain_witness":
                    self.on_witness(msg)
            except Exception as e:
                self.log(f"a witness message could not be used ({e!r})")


def _seq(query: dict, name: str):
    value = query.get(name)
    if value is None or value == "":
        return None
    if not (value.isascii() and value.isdigit()) or len(value) > 12 or int(value) < 1:
        raise _api_error()(HTTPStatus.BAD_REQUEST, f"{name} must be a record number, like 4127")
    return int(value)


def _api_error():
    from board.serve import ApiError   # here, not at the top: board/serve.py imports this module
    return ApiError


def routes(keeper: Keeper) -> dict:
    """The three endpoints, for make_server(routes=...). Mounted endpoints answer only on the board's
    own networks, which is what makes the prove-it check the operator's."""
    ApiError = _api_error()

    def chain(request):
        return keeper.status()

    def verify(request):
        first, last = _seq(request.query, "from"), _seq(request.query, "to")
        if first is not None and last is not None and last < first:
            raise ApiError(HTTPStatus.BAD_REQUEST, "to is before from")
        try:
            return keeper.store.verify(first, last)
        except ValueError as e:
            raise ApiError(HTTPStatus.BAD_REQUEST, str(e)) from None

    def tail(request):
        n = request.query.get("n", "40")
        if not (n.isascii() and n.isdigit()) or len(n) > 6 or int(n) < 1:
            raise ApiError(HTTPStatus.BAD_REQUEST, "n must be a whole number from 1, like 40")
        return {"records": keeper.store.tail(int(n))}

    def prove(request):
        ask = request.json() if request.body and request.body.strip() else {}
        if not isinstance(ask, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, 'send {} or {"n": 600, "seq": 3827}')
        n, seq = ask.get("n", 600), ask.get("seq")
        if type(n) is not int or n < 1 or not (seq is None or (type(seq) is int and seq >= 1)):
            raise ApiError(HTTPStatus.BAD_REQUEST, "n and seq are whole numbers from 1")
        try:
            return keeper.store.prove(n, seq)
        except ValueError as e:
            none_yet = "no sealed record" in str(e)
            raise ApiError(HTTPStatus.CONFLICT if none_yet else HTTPStatus.BAD_REQUEST, str(e)) from None

    return {("GET", "/chain"): chain, ("GET", "/chain/verify"): verify, ("GET", "/chain/tail"): tail,
            ("POST", "/chain/prove"): prove}


def start(store, keys=None, bus=BUS, listen=LISTEN):
    """Start the keeper's two threads. Returns (keeper, stop): set stop to end them."""
    out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    keeper = Keeper(store, keys, send=lambda data: out.sendto(data, bus))
    stop = threading.Event()
    threading.Thread(target=keeper.run, args=(stop,), name="chain", daemon=True).start()
    if listen is not None:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(listen)
        except OSError as e:
            keeper.log(f"can't listen for witnesses on {listen[0]}:{listen[1]} ({e}); signatures will not be stored")
        else:
            threading.Thread(target=keeper.listen, args=(sock, stop), name="witnesses", daemon=True).start()
    return keeper, stop
