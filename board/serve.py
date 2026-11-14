"""Web server for the screen.

    python board/serve.py
    python board/serve.py --host 192.168.77.2 --port 8080

Serves the built screen from web/dist, /nodes.json from radio/nodes.json and
/proof.json from proof/proof.json (CONTRACTS.md sections 2, 3 and 7). Both JSON
files are read on every request, so new measurements show up without a restart.
Until proof/proof.json exists, /proof.json is the section 7 shape with every
value null, which the screen shows as "__".

Standard library only.
"""
import argparse
import copy
import functools
import json
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DIST = REPO / "web" / "dist"
NODES = REPO / "radio" / "nodes.json"
PROOF = REPO / "proof" / "proof.json"

# CONTRACTS.md section 7 with nothing measured yet.
EMPTY_PROOF = {
    "zone": {"correct": None, "total": None, "ci95": None, "sessions": None, "walkers": None,
             "method": None},
    "threshold_zone": {"correct": None, "total": None},
    "person_vs_object": {"correct": None, "total": None, "tray_placements": None},
    "false_alarms_per_min": None,
    "train_s": None,
    "ms_per_decision": {"p50": None, "p95": None},
    "watts": {"idle": None, "teaching": None, "radio_only": None, "source": None},
    "bytes_out": None,
    "images_stored": None,
    "models_on_board": None,
    "measured_at": None,
    "commit": None,
}


def empty_proof() -> dict:
    return copy.deepcopy(EMPTY_PROOF)


class Handler(SimpleHTTPRequestHandler):
    # Don't trust the OS table: some systems map .js to text/plain, and browsers
    # refuse to run module scripts served that way.
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".html": "text/html; charset=utf-8",
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".css": "text/css",
        ".json": "application/json",
        ".svg": "image/svg+xml",
        ".wasm": "application/wasm",
        ".woff2": "font/woff2",
    }

    def do_GET(self):
        self._route(head=False)

    def do_HEAD(self):
        self._route(head=True)

    def _route(self, head: bool):
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        if path == "/nodes.json":
            return self._nodes(head)
        if path == "/proof.json":
            return self._proof(head)
        if not Path(self.directory).is_dir():
            return self._json({"error": "web/dist is not built yet"}, head,
                              HTTPStatus.SERVICE_UNAVAILABLE)
        return super().do_HEAD() if head else super().do_GET()

    def _nodes(self, head: bool):
        try:
            body = self.server.nodes_path.read_bytes()
            json.loads(body)
        except FileNotFoundError:
            return self._json({"error": "radio/nodes.json not found"}, head, HTTPStatus.NOT_FOUND)
        except (OSError, ValueError) as e:
            self.log_error("bad nodes.json: %s", e)
            return self._json({"error": "radio/nodes.json is not valid JSON"}, head,
                              HTTPStatus.SERVICE_UNAVAILABLE)
        self._send(body, head)

    def _proof(self, head: bool):
        try:
            body = self.server.proof_path.read_bytes()
            json.loads(body)
        except FileNotFoundError:
            return self._json(empty_proof(), head)
        except (OSError, ValueError) as e:
            self.log_error("bad proof.json, serving nulls: %s", e)
            return self._json(empty_proof(), head)
        self._send(body, head)

    def _json(self, obj, head: bool, status=HTTPStatus.OK):
        self._send(json.dumps(obj).encode(), head, status)

    def _send(self, body: bytes, head: bool, status=HTTPStatus.OK):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def end_headers(self):
        # The kiosk must pick up a new build or new numbers on reload.
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def list_directory(self, path):
        self.send_error(HTTPStatus.NOT_FOUND)
        return None

    def log_request(self, code="-", size="-"):
        # Only failures go to the journal; the screen polls a lot.
        if isinstance(code, HTTPStatus):
            code = code.value
        if str(code).isdigit() and int(code) >= 400:
            super().log_request(code, size)


def make_server(host="0.0.0.0", port=8080, dist=DIST, nodes=NODES, proof=PROOF):
    handler = functools.partial(Handler, directory=str(dist))
    server = ThreadingHTTPServer((host, port), handler)
    server.nodes_path = Path(nodes)
    server.proof_path = Path(proof)
    return server


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Serve the screen, /nodes.json and /proof.json")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--dist", default=str(DIST), help="built screen folder")
    ap.add_argument("--nodes", default=str(NODES))
    ap.add_argument("--proof", default=str(PROOF))
    args = ap.parse_args(argv)

    server = make_server(args.host, args.port, args.dist, args.nodes, args.proof)
    host, port = server.server_address[:2]
    print(f"serve: http://{host}:{port} from {args.dist}", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
