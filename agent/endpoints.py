"""The board's records as web handlers: GET /history and GET /report (CONTRACTS.md section 10), and
GET /ask/last (the most recent story answer, from memory; null when none was asked since start).

board/serve.py mounts them with its own rules (our networks only, always JSON, one way to read
from_t / to_t):

    serve.make_server(..., routes=endpoints.routes())

A handler gets serve's Request and returns a dict; a bad request is serve.ApiError.
"""
import threading

from store import DB, Store
from . import report as reports
from .ask import LLM_URL, last_story

MODEL = threading.Lock()   # llama-server has one slot: one report is written at a time
# GET /report answers from the template at once. The on-board model may only improve the wording, and only
# if its text is back within this long; on the board it rarely is, and then the template stands.
REPORT_WAIT_S = 0.5


def history(store: Store):
    def handler(req):
        from board import serve
        from_t, to_t = serve.time_span(req.query)        # both needed, at most 30 minutes
        try:
            return store.history(from_t, to_t)
        except ValueError as e:
            raise serve.ApiError(400, str(e)) from None
    return handler


def report(store: Store, llm=None, **kw):
    def handler(req):
        from board import serve
        from_t, to_t = serve.time_span(req.query, max_ms=None, required=False)   # neither = the last armed stretch
        # Never queued behind another report's wait for the model: if the model is taken, the template alone.
        free = llm is not None and MODEL.acquire(blocking=False)
        try:
            out = reports.report(store, llm if free else None, from_t, to_t, **{"timeout_s": REPORT_WAIT_S, **kw})
        finally:
            if free:
                MODEL.release()
        if out is None:
            raise serve.ApiError(404, "the space has not been armed, so there is no report")
        return out
    return handler


def ask_last(req):
    """GET /ask/last: the most recent story answer as POST /ask returned it, plus its question and asked_t, or None."""
    return last_story()


def routes(db=None, llm=None) -> dict:
    """{(method, path): handler} for serve.make_server, from the store's file and the on-board model."""
    store = Store(db or DB)
    return {("GET", "/history"): history(store), ("GET", "/report"): report(store, reports.Writer(llm or LLM_URL, timeout_s=REPORT_WAIT_S)),
            ("GET", "/ask/last"): ask_last}
