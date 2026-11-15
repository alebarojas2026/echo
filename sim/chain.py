"""A simulated sealed record and its witnesses (CONTRACTS.md section 13), for building the screens
without the kit.

    python -m sim.chain witness_silent --at 30      # what GET /chain would answer 30 s into that path
    python -m sim.chain chain_broken --at 20 --verify

A path with a "chain" block gets one: the fake feed sends chain_head every 5 s and a chain_witness
from each witness that is signing, and the fake brain's state carries `chain`. The block:

    "chain": {"witnesses": ["pi5", "pi5b"],                      # who is enrolled (these two by default)
              "silent": [{"node": "pi5b", "t_on": 8, "t_off": 34}],   # that witness signs nothing in between
              "bad": {"t": 12, "seq": 9}}                         # from 12 s on the check fails at record 9

Everything here is made up and carries src "sim": the records are one a second plus the witnesses'
own, hashed the way the store hashes (so the chain really does verify, and really does fail at the
record a "bad" block names), but the signatures are not signatures of anything. Nothing here says
how the real chain or the real witnesses behave.
"""
import argparse
import base64
import hashlib
import json

from store.chain import ZERO, canon, record_hash, verify_rows

HEAD_EVERY_S = 5.0
VERIFY_EVERY_S = 30.0
SILENT_AFTER_S = 15.0
WITNESSES = ("pi5", "pi5b")


def fake_sig(node: str, seq: int, digest: str) -> str:
    """64 bytes in base64 that look like a signature and are not one."""
    seed = f"sim|{node}|{seq}|{digest}".encode()
    return base64.b64encode(hashlib.sha256(seed).digest() + hashlib.sha256(seed[::-1]).digest()).decode()


class Chain:
    """The chain of one path, advanced in path time. start_ms: the epoch ms of the path's t = 0."""

    def __init__(self, spec: dict, start_ms: int = 0):
        self.spec, self.start_ms = spec or {}, start_ms
        self.nodes = list(self.spec.get("witnesses", WITNESSES))
        self.rows = []          # (seq, t ms, kind, body text, prev, hash), as the store keeps them
        self.witness = {n: {"last_seq": None, "last_t": None, "sig_ok": False, "silent": False, "signed_at": None}
                        for n in self.nodes}
        self.second = self.heads = 0     # whole seconds sealed, heads sent
        self.out = []                    # the bus messages not collected yet (internal events, see wire.py)
        self.altered = False

    def _ms(self, t: float) -> int:
        return self.start_ms + round(t * 1000)

    def _seal(self, t: float, kind: str, body: dict) -> int:
        seq = len(self.rows) + 1
        prev, text = self.rows[-1][5] if self.rows else ZERO, canon(body)
        self.rows.append((seq, self._ms(t), kind, text, prev, record_hash(seq, self._ms(t), kind, text, prev)))
        return seq

    def _is_silenced(self, node: str, t: float) -> bool:
        return any(s.get("node") == node and s.get("t_on", 0.0) <= t < s.get("t_off", float("inf"))
                   for s in self.spec.get("silent") or [])

    def advance(self, t: float) -> None:
        """Seal what the path has saved up to t: a record each second, a head and its signatures every 5 s."""
        bad = self.spec.get("bad")
        while self.second <= t:
            at = float(self.second)
            self._seal(at, "second", {"src": "sim", "n": self.second})
            if bad and not self.altered and at >= bad["t"] and len(self.rows) >= bad["seq"]:
                seq, ms, kind, text, prev, digest = self.rows[bad["seq"] - 1]      # an edit of a stored record
                self.rows[bad["seq"] - 1] = (seq, ms, kind, canon({**json.loads(text), "altered": True}), prev, digest)
                self.altered = True
            for node, w in self.witness.items():     # the 15 s rule
                since = w["signed_at"] if w["signed_at"] is not None else 0.0
                if not w["silent"] and at - since >= SILENT_AFTER_S:
                    w["silent"] = True
                    self._seal(at, "witness_silent", {"node": node})
            if self.second % HEAD_EVERY_S == 0:
                self._head(at)
            self.second += 1

    def _head(self, at: float) -> None:
        seq, digest = self.rows[-1][0], self.rows[-1][5]
        self.heads += 1
        signing = [n for n in self.nodes if not self._is_silenced(n, at)]
        self.out.append({"type": "chain_head", "t": at, "seq": seq, "hash": digest, **self.counts(at)})
        for node in signing:
            w = self.witness[node]
            sig = fake_sig(node, seq, digest)
            self._seal(at, "witness", {"node": node, "seq": seq, "hash": digest, "t": self._ms(at), "sig": sig})
            if w["silent"]:
                self._seal(at, "witness_back", {"node": node})
            w.update(last_seq=seq, last_t=self._ms(at), sig_ok=True, silent=False, signed_at=at)
            self.out.append({"type": "chain_witness", "t": at, "node": node, "seq": seq, "hash": digest, "sig": sig})

    def pop(self) -> list:
        out, self.out = self.out, []
        return out

    # ---- what the board would say ----

    def _checked(self, t: float):
        """(ok, first_bad_seq) as of the last 30 s check before t, or None before the first."""
        ok, _, bad = verify_rows(self.rows, ZERO)
        spec = self.spec.get("bad")
        if spec and not ok and t < spec["t"]:
            return True, None
        return ok, bad

    def counts(self, t: float) -> dict:
        ok, _ = self._checked(t)
        return {"verified": ok, "witnesses_ok": sum(1 for w in self.witness.values() if w["sig_ok"] and not w["silent"]),
                "witnesses": len(self.nodes)}

    def state(self, t: float) -> dict:
        """state.chain at t."""
        self.advance(t)
        return {"seq": self.rows[-1][0], "hash8": self.rows[-1][5][:8], **self.counts(t)}

    def status(self, t: float) -> dict:
        """The answer of GET /chain at t."""
        self.advance(t)
        ok, bad = self._checked(t)
        return {"head": {"seq": self.rows[-1][0], "hash": self.rows[-1][5]}, "records": len(self.rows),
                "since_t": self.rows[0][1], "verified": ok, "last_verify_t": self._ms(t), "first_bad_seq": bad,
                "witnesses": [{"node": n, "last_seq": w["last_seq"], "last_t": w["last_t"], "sig_ok": w["sig_ok"],
                               "silent": w["silent"]} for n, w in sorted(self.witness.items())],
                "first_seq": 1, "anchor": None, "unsealed": 0}

    def verify(self, t: float) -> dict:
        """The answer of GET /chain/verify at t (ms is 0: nothing was timed)."""
        self.advance(t)
        ok, checked, bad = verify_rows(self.rows, ZERO)
        return {"ok": ok, "checked": checked, "first_bad_seq": bad, "ms": 0, "from": 1, "to": len(self.rows)}

    def records(self) -> list:
        return [{"seq": s, "t": ms, "kind": kind, "body": json.loads(text), "prev": prev, "hash": digest}
                for s, ms, kind, text, prev, digest in self.rows]


def of(path: dict, start_ms: int = 0):
    """The path's chain, or None when the path has no "chain" block."""
    return Chain(path["chain"], start_ms) if isinstance(path.get("chain"), dict) else None


def main(argv=None) -> None:
    from . import fake
    ap = argparse.ArgumentParser(description="What the board's /chain would answer during a simulated path")
    ap.add_argument("path", help="a name in sim/paths/ with a chain block (witnesses, witness_silent, chain_broken)")
    ap.add_argument("--at", type=float, default=None, help="seconds into the path (default: its end)")
    ap.add_argument("--verify", action="store_true", help="print the /chain/verify answer instead")
    args = ap.parse_args(argv)
    path = fake.load_path(args.path)
    chain = of(path, start_ms=1_763_149_500_000)
    if chain is None:
        raise SystemExit(f"{args.path} has no chain block")
    t = path["duration_s"] if args.at is None else args.at
    print(json.dumps(chain.verify(t) if args.verify else chain.status(t), indent=1))


if __name__ == "__main__":
    main()
