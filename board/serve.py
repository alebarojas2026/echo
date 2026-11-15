"""Web server for the screen.

    python board/serve.py
    python board/serve.py --host 192.168.77.2 --port 8080

Serves the built screen from web/dist, /nodes.json from radio/nodes.json and
/proof.json from proof/proof.json (CONTRACTS.md sections 2, 3 and 7). Both JSON
files are read on every request, so new measurements show up without a restart.
Until proof/proof.json exists, /proof.json is the section 7 shape with every
value null, which the screen shows as "__".

/layout is for the operator's align mode (#510): GET gives the saved room alignment and
the hall beacons' positions, POST saves them (board/layout.py says what may be sent). They
are for drawing only and live in data/layout.local.json; /nodes.json carries the saved hall
positions, and nothing else in it changes. POST is taken only from the board itself, the
Ethernet link and the sensing hotspot (where the laptop is), and only as JSON.

POST /ask with {"question": "..."} asks the room: agent/ask.py picks a tool with the on-board
model and answers from the store (store/). The reply is {answer, rows, tool, args, picked_by,
src, ms}. One question at a time, because llama-server has one slot. Taken from the same
networks as a layout save.

Other lanes' JSON endpoints (GET /history and GET /report from the store, POST /ask; CONTRACTS.md
section 10) are mounted, not written in here: make_server(routes={("GET", "/history"): fn}). A
handler gets a Request (query, body, client) and returns a dict, sent as JSON; it raises
ApiError(status, "plain message") for a bad request, answered {"error": message}. time_span()
reads from_t/to_t the same way for every handler, with the 30-minute limit. Mounted endpoints
answer only on the board's own networks, like a layout save; anything else a handler raises is
a 500 with a JSON error, and the server keeps running.

Standard library only.
"""
import argparse
import copy
import functools
import ipaddress
import json
import sys
import threading
import urllib.parse
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:  # the unit runs this file as a script: board.layout must still import
    sys.path.insert(0, str(REPO))

from board import layout  # noqa: E402

DIST = REPO / "web" / "dist"
NODES = REPO / "radio" / "nodes.json"
PROOF = REPO / "proof" / "proof.json"
LAYOUT = REPO / "data" / "layout.local.json"
# Who may save a layout: the board itself, the Ethernet link to the Pi (the laptop on the hotspot
# arrives from 192.168.77.1, Pi A forwards it) and the sensing hotspot (CONTRACTS.md section 2).
MAX_ASK_BYTES = 2048
SAVE_FROM = [ipaddress.ip_network(n) for n in ("127.0.0.0/8", "192.168.77.0/24", "10.42.0.0/24")]
MAX_API_BODY = 8192
SPAN_MAX_MS = 30 * 60 * 1000    # /history answers at most 30 minutes per call (CONTRACTS.md section 10)


class ApiError(Exception):
    """Raised by a mounted handler: answered as {"error": message} with this status."""

    def __init__(self, status, message: str):
        super().__init__(message)
        self.status, self.message = HTTPStatus(status), message


class Request:
    """What a mounted handler gets. query: one string per name. body: the raw POST body (None on
    GET). client: the caller's address."""

    def __init__(self, query: dict, body, client: str):
        self.query, self.body, self.client = query, body, client

    def json(self):
        try:
            return json.loads(self.body)
        except (TypeError, ValueError):
            raise ApiError(HTTPStatus.BAD_REQUEST, "not JSON") from None


def _epoch_ms(query: dict, name: str) -> int:
    v = query[name]
    if not (v.isascii() and v.isdigit()) or len(v) > 16:
        raise ApiError(HTTPStatus.BAD_REQUEST, f"{name} must be a time in epoch milliseconds, like 1763149300000")
    return int(v)


def time_span(query: dict, max_ms=SPAN_MAX_MS, required=True):
    """(from_t, to_t) in epoch ms from ?from_t=&to_t=, or (None, None) when both are left out and
    required is False. to_t - from_t may be at most max_ms (None: no limit)."""
    given = [k for k in ("from_t", "to_t") if k in query]
    if not given and not required:
        return None, None
    if len(given) < 2:
        raise ApiError(HTTPStatus.BAD_REQUEST, "give both from_t and to_t" + ("" if required else ", or neither"))
    from_t, to_t = _epoch_ms(query, "from_t"), _epoch_ms(query, "to_t")
    if to_t < from_t:
        raise ApiError(HTTPStatus.BAD_REQUEST, "to_t is before from_t")
    if max_ms is not None and to_t - from_t > max_ms:
        raise ApiError(HTTPStatus.BAD_REQUEST,
                       f"at most {max_ms // 60000} minutes per call; this asks for "
                       f"{(to_t - from_t) / 60000:.1f} minutes")
    return from_t, to_t

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

    def do_POST(self):
        self._body_read = False
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        if ("POST", path) in self.server.routes:
            return self._api("POST", path, head=False)
        if path not in ("/layout", "/ask"):
            if ("GET", path) in self.server.routes:
                return self._json({"error": "use GET"}, False, HTTPStatus.METHOD_NOT_ALLOWED)
            return self._json({"error": "not found"}, False, HTTPStatus.NOT_FOUND)
        if not self._ours():
            return self._json({"error": "taken only from the board's own networks"}, False,
                              HTTPStatus.FORBIDDEN)
        if path == "/ask":
            return self._ask()
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            return self._json({"error": "send JSON (Content-Type: application/json)"}, False,
                              HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self._json({"error": "Content-Length needed"}, False, HTTPStatus.LENGTH_REQUIRED)
        if length > layout.MAX_BODY:
            return self._json({"error": "too big"}, False, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        try:
            nodes_doc = self._nodes_doc()
        except (OSError, ValueError):
            return self._json({"error": "radio/nodes.json can't be read"}, False, HTTPStatus.SERVICE_UNAVAILABLE)
        try:
            change = layout.clean(json.loads(self._read(length)), nodes_doc)
        except layout.Invalid as e:
            return self._json({"error": str(e)}, False, HTTPStatus.BAD_REQUEST)
        except ValueError:
            return self._json({"error": "not JSON"}, False, HTTPStatus.BAD_REQUEST)
        try:
            self.server.layout.save(change)
        except OSError as e:
            self.log_error("can't save the layout: %s", e)
            return self._json({"error": "can't save the layout on the board"}, False,
                              HTTPStatus.INTERNAL_SERVER_ERROR)
        return self._json(self.server.layout.view(nodes_doc), False)

    def _ours(self) -> bool:
        """The request comes from the board itself, the Ethernet link or the sensing hotspot."""
        try:
            client = ipaddress.ip_address(self.client_address[0])
        except ValueError:
            return False
        return any(client in net for net in SAVE_FROM)

    def _ask(self):
        try:
            size = int(self.headers.get("Content-Length") or 0)
            if not 0 < size <= MAX_ASK_BYTES:
                raise ValueError("body size")
            question = json.loads(self._read(size))["question"]
            if not isinstance(question, str) or not question.strip():
                raise ValueError("question")
        except (ValueError, KeyError, TypeError):
            return self._json({"error": 'send {"question": "..."}'}, False, HTTPStatus.BAD_REQUEST)
        if self.server.ask is None:
            return self._json({"error": "ask is not set up on this server"}, False,
                              HTTPStatus.SERVICE_UNAVAILABLE)
        try:
            with self.server.ask_lock:
                reply = self.server.ask(question)
        except Exception as e:
            self.log_error("ask failed: %s", e)
            return self._json({"error": "the room could not answer"}, False,
                              HTTPStatus.INTERNAL_SERVER_ERROR)
        self._json(reply, False)

    def _api(self, method: str, path: str, head: bool):
        """Answer a mounted endpoint: always JSON, whatever the handler does."""
        if not self._ours():
            return self._json({"error": "answered only on the board's own networks"}, head, HTTPStatus.FORBIDDEN)
        try:
            body = self._body() if method == "POST" else None
            query = {}
            for name, values in urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query,
                                                      keep_blank_values=True).items():
                if len(values) > 1:
                    raise ApiError(HTTPStatus.BAD_REQUEST, f"{name} is given more than once")
                query[name] = values[0]
            reply = self.server.routes[(method, path)](Request(query, body, self.client_address[0]))
            if not isinstance(reply, dict):
                raise TypeError(f"the handler returned {type(reply).__name__}, not a dict")
        except ApiError as e:
            return self._json({"error": e.message}, head, e.status)
        except Exception as e:  # a bad handler must not take the screen's server down
            self.log_error("%s %s failed: %r", method, path, e)
            return self._json({"error": "the board could not answer"}, head, HTTPStatus.INTERNAL_SERVER_ERROR)
        self._json(reply, head)

    def _body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            raise ApiError(HTTPStatus.LENGTH_REQUIRED, "Content-Length needed") from None
        if not 0 <= length <= MAX_API_BODY:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "too big")
        return self._read(length)

    def _read(self, length: int) -> bytes:
        self._body_read = True
        return self.rfile.read(length)

    def _drain(self):
        """Read a POST body nothing has read yet. Answering early (403, 404, ...) and closing with
        the body still unread resets the connection on some systems, and the caller sees that
        instead of the answer."""
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return
        if 0 < length <= MAX_API_BODY:
            try:
                self._read(length)
            except OSError:
                pass

    def _nodes_doc(self):
        return json.loads(self.server.nodes_path.read_bytes())

    def _route(self, head: bool):
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        if path == "/nodes.json":
            return self._nodes(head)
        if path == "/proof.json":
            return self._proof(head)
        if ("GET", path) in self.server.routes:
            return self._api("GET", path, head)
        if path == "/layout":
            try:
                return self._json(self.server.layout.view(self._nodes_doc()), head)
            except (OSError, ValueError):
                return self._json({"error": "radio/nodes.json can't be read"}, head,
                                  HTTPStatus.SERVICE_UNAVAILABLE)
        if not Path(self.directory).is_dir():
            return self._json({"error": "web/dist is not built yet"}, head,
                              HTTPStatus.SERVICE_UNAVAILABLE)
        return super().do_HEAD() if head else super().do_GET()

    def _nodes(self, head: bool):
        try:
            body = self.server.nodes_path.read_bytes()
            doc = json.loads(body)
            stored = self.server.layout.load()
            if stored["hall"]:  # the saved hall positions; with none, the file's own bytes
                body = json.dumps(layout.overlay(doc, stored), indent=2).encode()
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
        if self.command == "POST" and not getattr(self, "_body_read", False):
            self._drain()
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


def make_server(host="0.0.0.0", port=8080, dist=DIST, nodes=NODES, proof=PROOF, layout_path=LAYOUT, ask=None,
                routes=None):
    """ask: a function question -> reply dict for POST /ask, or None to answer 503.
    routes: {(method, path): handler} for the mounted JSON endpoints (see the top of this file)."""
    handler = functools.partial(Handler, directory=str(dist))
    server = ThreadingHTTPServer((host, port), handler)
    server.nodes_path = Path(nodes)
    server.proof_path = Path(proof)
    server.layout = layout.Store(layout_path)
    server.ask, server.ask_lock = ask, threading.Lock()
    server.routes = dict(routes or {})
    return server


def room_ask(db=None, llm=None):
    """question -> reply, from the store and the on-board model. None if agent/ or store/ is missing."""
    try:
        from agent.ask import LLM_URL, Picker, ask
        from store import DB, Store
    except ImportError as e:
        print(f"serve: /ask is off ({e})", file=sys.stderr, flush=True)
        return None
    store, picker = Store(db or DB), Picker(llm or LLM_URL)
    return lambda question: ask(question, store, picker)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Serve the screen, /nodes.json and /proof.json")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--dist", default=str(DIST), help="built screen folder")
    ap.add_argument("--nodes", default=str(NODES))
    ap.add_argument("--proof", default=str(PROOF))
    ap.add_argument("--layout", default=str(LAYOUT), help="where align mode's saves are kept")
    ap.add_argument("--store", default=None, help="the store's SQLite file, for /ask")
    ap.add_argument("--llm", default=None, help="llama-server base URL, for /ask")
    args = ap.parse_args(argv)

    server = make_server(args.host, args.port, args.dist, args.nodes, args.proof, args.layout,
                         ask=room_ask(args.store, args.llm))
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
