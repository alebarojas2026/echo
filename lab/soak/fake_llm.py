"""A stand-in for llama-server's chat endpoint, for the soak: no model, seeded answers.

    python lab/soak/fake_llm.py --port 8091 --seed 3

POST /v1/chat/completions. With a response_format schema (the agent's tool pick) it answers a
JSON object drawn from the schema's enums; without one (the narrator) a short sentence. A share
of replies are slow (past the callers' timeouts), broken JSON, or an HTTP 500, like a busy model.
GET /health answers {"status": "ok"}. Dev only.
"""
import argparse
import json
import random
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SENTENCES = ["Someone just stepped up to the desk.", "They moved to the other side.", "Nobody is here now.",
             "The camera is off; the radio carries on.", "Still standing on the right."]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send(200, {"status": "ok"})

    def do_POST(self):
        rng, cfg = self.server.rng, self.server.cfg
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        except ValueError:
            return self._send(400, {"error": "bad json"})
        roll = rng.random()
        if roll < cfg.slow:
            time.sleep(rng.uniform(8.5, 15))
        elif roll < cfg.slow + cfg.fail:
            return self._send(500, {"error": "slot busy"})
        schema = ((body.get("response_format") or {}).get("schema")) or None
        if schema:
            if rng.random() < cfg.broken:
                content = '{"tool": "presence", "minutes": '
            else:
                props = schema.get("properties", {})
                pick = {}
                for k, p in props.items():
                    if "enum" in p:
                        pick[k] = rng.choice(p["enum"])
                    elif p.get("type") == "integer":
                        pick[k] = rng.randint(p.get("minimum", 0), p.get("maximum", 60))
                content = json.dumps(pick)
        else:
            time.sleep(rng.uniform(0.2, 2.5))   # a sentence takes a while on the board
            content = rng.choice(SENTENCES)
        self._send(200, {"choices": [{"message": {"role": "assistant", "content": content}}],
                         "model": "fake-soak-model"})


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8091)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--slow", type=float, default=0.05)
    ap.add_argument("--fail", type=float, default=0.05)
    ap.add_argument("--broken", type=float, default=0.05)
    a = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    srv.rng, srv.cfg = random.Random(a.seed), a
    srv.serve_forever()


if __name__ == "__main__":
    main()
