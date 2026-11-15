"""The Pi as a witness: it signs the board's chain head with a key that never leaves this Pi (#866).

    python3 -m pi.witness --init      # once: make this Pi's key pair, print its public key line
    python3 -m pi.witness --pubkey    # print that line again
    python3 -m pi.witness             # what the unit radio-sight-witness runs

The board seals its records in a hash chain and says where the chain stands every 5 s:
chain_head {seq, hash, t}. This program asks the bus for those (a chain_sub every 5 s, from the one
UDP socket the answers come back on, so it also works from Pi B behind Pi A's hotspot), signs the
bytes "node|seq|hash|t" with this Pi's Ed25519 private key and answers
chain_witness {node, seq, hash, t, sig}; sig is the 64-byte signature in lowercase hex.

Signing is the `openssl` already on the Pi (OpenSSL 3), nothing else:
    openssl genpkey -algorithm ed25519 -out witness_ed25519.pem                 # --init
    openssl pkey -in witness_ed25519.pem -pubout                                # the public key
    openssl pkeyutl -sign -inkey witness_ed25519.pem -rawin -in MSG             # each head
    openssl pkeyutl -verify -pubin -inkey PUB.pem -rawin -in MSG -sigfile SIG   # the board's check
Ed25519 signs the message in one go, so openssl needs it as a file (-in), not on stdin.

The key and this Pi's own record of what it signed live in data/witness/ (WITNESS_DIR), which git
ignores: witness_ed25519.pem (mode 600, never printed, never sent) and signed.jsonl, one line per
signature {seq, hash, t, sig}, only ever appended to. A head whose seq is lower than the last one
signed, or the same seq with another hash, is the chain stepping back: the line then also carries
back_from {seq, hash}, and it is written before the signature is sent. If the line can't be written
the signature is not sent.

With no key the program says "not enrolled" and ends (exit 0): the witness is optional and the
radio readers on this Pi don't depend on it. It is its own small process: it wakes for a head every
5 s and for one status line every 10 s (journalctl -u radio-sight-witness).

Settings, all optional (.env at the repo root): RADIO_NODE (pi5), BUS_HOST (192.168.77.2),
BUS_PORT (5600), WITNESS_DIR (data/witness), OPENSSL (openssl).
"""
from __future__ import annotations

import argparse
import base64
import collections
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KEY_NAME = "witness_ed25519.pem"
LOG_NAME = "signed.jsonl"
SUB_S = 5.0        # ask the bus again this often (it forgets a witness after 30 s)
STATUS_S = 10.0    # one status line this often
QUIET_S = 15.0     # no head for this long: the status line says so
HASH = re.compile(r"^[0-9a-f]{64}$")
NODE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def env_value(key: str, default: str, env_file=None) -> str:
    """KEY from the environment, else from the repo's .env (a hand-run command has no systemd to read it)."""
    if os.environ.get(key):
        return os.environ[key]
    try:
        lines = Path(env_file or REPO / ".env").read_text(encoding="utf-8").splitlines()
    except OSError:
        return default
    for line in lines:
        m = re.match(rf"\s*(?:export\s+)?{key}=(.*)", line)
        if m and m.group(1).strip().strip("'\""):
            return m.group(1).strip().strip("'\"")
    return default


def folder() -> Path:
    return Path(env_value("WITNESS_DIR", str(REPO / "data" / "witness")))


def openssl(*args: str, data_out: bool = False):
    """Run openssl; returns stdout (bytes). Raises RuntimeError with openssl's own words when it fails."""
    try:
        r = subprocess.run([env_value("OPENSSL", "openssl"), *args], capture_output=True, timeout=10)
    except FileNotFoundError:
        raise RuntimeError("openssl is not installed") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError("openssl gave no answer in 10 s") from None
    if r.returncode != 0:
        words = r.stderr.decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(f"openssl {args[0]} failed: {words[0] if words else r.returncode}")
    return r.stdout


def public_line(node: str, where: Path) -> str:
    """This Pi's line for the board's key file: "node": "<the public key PEM's base64 body>"."""
    pem = openssl("pkey", "-in", str(where / KEY_NAME), "-pubout").decode("ascii")
    body = "".join(line for line in pem.splitlines() if line and not line.startswith("-----"))
    base64.b64decode(body, validate=True)
    return f'"{node}": "{body}"'


def init(node: str, where: Path, force: bool = False) -> str:
    """Make the key pair; returns the public line. Refuses to replace a key unless force."""
    key = where / KEY_NAME
    if key.exists() and not force:
        raise FileExistsError(f"this Pi already has a witness key ({key}); --pubkey prints its public key, "
                              "--init --force replaces it (the board then needs the new public key)")
    where.mkdir(parents=True, exist_ok=True)
    old = os.umask(0o077)
    try:
        key.unlink(missing_ok=True)
        openssl("genpkey", "-algorithm", "ed25519", "-out", str(key))
    finally:
        os.umask(old)
    os.chmod(key, 0o600)
    os.chmod(where, 0o700)
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        # Made with sudo: hand the folder to the checkout's owner, the user the unit runs as.
        owner = REPO.stat()
        for path in (where, key):
            os.chown(path, owner.st_uid, owner.st_gid)
    return public_line(node, where)


def message(node: str, seq: int, hash_: str, t: int) -> bytes:
    """The bytes a witness signs."""
    return f"{node}|{seq}|{hash_}|{t}".encode()


class Signer:
    """sign(bytes) -> the 64-byte Ed25519 signature, made by openssl with this Pi's key."""

    def __init__(self, where: Path):
        self.key = where / KEY_NAME
        self.scratch = where / ".msg"

    def __call__(self, data: bytes) -> bytes:
        self.scratch.write_bytes(data)
        sig = openssl("pkeyutl", "-sign", "-inkey", str(self.key), "-rawin", "-in", str(self.scratch))
        if len(sig) != 64:
            raise RuntimeError(f"openssl gave {len(sig)} bytes, not a 64-byte Ed25519 signature")
        return sig


class SignedLog:
    """signed.jsonl: one line per signature, appended and flushed, never rewritten."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def last(self):
        """The last line written, or None (no file yet, or its end can't be read)."""
        try:
            with open(self.path, "rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - 4096))
                lines = f.read().splitlines()
            entry = json.loads(lines[-1])
            return entry if isinstance(entry.get("seq"), int) and isinstance(entry.get("hash"), str) else None
        except (OSError, ValueError, IndexError, AttributeError):
            return None

    def append(self, entry: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")
            f.flush()
            os.fsync(f.fileno())


def _whole(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


class Witness:
    """Turns chain_head datagrams into chain_witness answers. No sockets in here."""

    def __init__(self, node: str, sign, log: SignedLog, say=lambda line: print(line, flush=True)):
        self.node, self.sign, self.log, self.say = node, sign, log, say
        last = log.last()
        self.last = (last["seq"], last["hash"], last.get("t")) if last else None
        self.answer = None                  # the datagram for self.last, if signed in this run
        self.signed = collections.deque()   # monotonic time of each signature in the last minute
        self.ignored = self.steps_back = self.failed = 0
        self.error = None
        self.head_at = None                 # monotonic time of the last good head

    def head(self, data: bytes, now: float | None = None):
        """One datagram from the bus. Returns the chain_witness to send (bytes), or None."""
        now = time.monotonic() if now is None else now
        try:
            msg = json.loads(data)
        except (ValueError, UnicodeDecodeError):
            msg = None
        if isinstance(msg, dict) and msg.get("type") == "chain_witness":
            return None   # another witness's answer, relayed: not ours to sign
        if not isinstance(msg, dict) or msg.get("type") != "chain_head":
            self.ignored += 1
            return None
        seq, hash_, t = msg.get("seq"), msg.get("hash"), msg.get("t")
        if not (_whole(seq) and seq >= 1 and isinstance(hash_, str) and HASH.match(hash_) and _whole(t) and t > 0):
            self.ignored += 1
            return None
        self.head_at = now
        if self.last == (seq, hash_, t) and self.answer:
            return self.answer   # the same head again: the same answer, nothing new to log
        entry = {"seq": seq, "hash": hash_, "t": t}
        if self.last and (seq < self.last[0] or (seq == self.last[0] and hash_ != self.last[1])):
            entry["back_from"] = {"seq": self.last[0], "hash": self.last[1]}
            self.steps_back += 1
            self.say(f"[pi.witness] the chain stepped back: head seq {seq} after signing seq {self.last[0]}; "
                     "noted in this Pi's log, then signed")
        try:
            entry["sig"] = self.sign(message(self.node, seq, hash_, t)).hex()
            self.log.append(entry)   # logged first: nothing is sent that this Pi has no record of
        except (OSError, RuntimeError) as e:
            self.failed += 1
            self.error = e
            return None
        self.error = None
        self.last = (seq, hash_, t)
        self.signed.append(now)
        self.answer = json.dumps({"v": 2, "type": "chain_witness", "node": self.node, "seq": seq, "hash": hash_,
                                  "t": t, "sig": entry["sig"], "src": "live"}, separators=(",", ":")).encode()
        return self.answer

    def status_line(self, now: float | None = None, bus_error=None) -> str:
        now = time.monotonic() if now is None else now
        while self.signed and now - self.signed[0] > 60:
            self.signed.popleft()
        line = (f"[pi.witness] {self.node}: last seq signed {self.last[0] if self.last else 'none'}, "
                f"{len(self.signed)} signatures a minute")
        if self.head_at is None:
            line += "; no head from the board yet"
        elif now - self.head_at >= QUIET_S:
            line += f"; no head from the board for {now - self.head_at:.0f} s"
        if bus_error:
            line += f"; can't reach the bus ({bus_error})"
        if self.error:
            line += f"; not signing: {self.error}"
        if self.failed or self.ignored or self.steps_back:
            line += f"; {self.failed} not signed, {self.ignored} ignored, {self.steps_back} steps back"
        return line


def run(witness: Witness, bus: tuple, seconds: float | None = None, stop=None, sub_every: float = SUB_S,
        status_every: float = STATUS_S) -> None:
    """Ask, sign and answer until `seconds` pass or `stop` (a threading.Event) is set. A bus that is
    away or a network that is down only costs a status line: the socket is opened again and asked again."""
    sub = json.dumps({"v": 2, "type": "chain_sub", "node": witness.node, "src": "live"}, separators=(",", ":"))
    sock = bus_ip = bus_error = None
    start = time.monotonic()
    next_sub, next_status = start, start + status_every
    try:
        while not (stop is not None and stop.is_set()):
            now = time.monotonic()
            if seconds is not None and now - start >= seconds:
                break
            if now >= next_sub:
                next_sub = now + sub_every
                try:
                    if sock is None:
                        bus_ip = socket.gethostbyname(bus[0])
                        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    sock.sendto((sub[:-1] + f',"t":{int(time.time() * 1000)}}}').encode(), (bus_ip, bus[1]))
                    bus_error = None
                except OSError as e:
                    bus_error = e
                    if sock is not None:
                        sock.close()
                    sock = None
            if now >= next_status:
                next_status = now + status_every
                witness.say(witness.status_line(now, bus_error))
            wait = max(0.02, min(next_sub, next_status, now + 1.0) - now)
            if sock is None:
                time.sleep(wait)
                continue
            sock.settimeout(wait)
            try:
                data, addr = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                time.sleep(0.05)   # nobody on the bus port yet (Windows says so here); the next ask finds out
                continue
            if addr[0] != bus_ip:
                witness.ignored += 1   # heads are taken from the bus only
                continue
            answer = witness.head(data)
            if answer:
                try:
                    sock.sendto(answer, (bus_ip, bus[1]))
                except OSError as e:
                    bus_error = e
    finally:
        if sock is not None:
            sock.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="This Pi as a witness: signs the board's chain head (openssl, Ed25519)")
    ap.add_argument("--node", help="which Pi this is (default: RADIO_NODE from .env, else pi5)")
    ap.add_argument("--init", action="store_true", help="make this Pi's key pair and print its public key line")
    ap.add_argument("--force", action="store_true", help="with --init: replace the key that is there")
    ap.add_argument("--pubkey", action="store_true", help="print the public key line again")
    ap.add_argument("--seconds", type=float, help="stop after this long (default: run until stopped)")
    args = ap.parse_args(argv)
    node = args.node or env_value("RADIO_NODE", "pi5")
    if not NODE.match(node):
        print(f"witness: '{node}' is not a node id", file=sys.stderr)
        return 2
    where = folder()
    try:
        if args.init:
            print(init(node, where, args.force))
            return 0
        if not (where / KEY_NAME).exists():
            if args.pubkey:
                print("witness: not enrolled: this Pi has no key yet; run: python3 -m pi.witness --init",
                      file=sys.stderr)
                return 1
            print(f"[pi.witness] {node}: not enrolled (no key in {where}); nothing to do. "
                  "To enrol: python3 -m pi.witness --init", flush=True)
            return 0
        if args.pubkey:
            print(public_line(node, where))
            return 0
        sign = Signer(where)
        sign(message(node, 1, "0" * 64, 1))   # the key can be read and openssl signs with it, or say why now
    except (FileExistsError, RuntimeError, OSError, ValueError) as e:
        print(f"witness: {e}", file=sys.stderr)
        return 1
    bus = (env_value("BUS_HOST", "192.168.77.2"), int(env_value("BUS_PORT", "5600")))
    witness = Witness(node, sign, SignedLog(where / LOG_NAME))
    print(f"[pi.witness] {node}: signing the board's chain head; asking the bus at {bus[0]}:{bus[1]}; "
          f"this Pi's record is {where / LOG_NAME}", flush=True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        run(witness, bus, seconds=args.seconds)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
