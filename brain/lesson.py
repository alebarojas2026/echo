"""The live lesson: the camera teaches the radio on whoever is standing there, in about 30 s.

The screen sends commands that already exist (CONTRACTS.md section 5):

    label_mode {mode: person}
    record_start {session, purpose: train, walker}     the person steps left and right, about 20 s
    train                                              the recording stays open: this starts the lesson
    ...                                                the camera is unplugged whenever they like
    record_stop

A `train` that arrives while a train recording is open fits from that recording as far as it has
got (with this place's earlier recordings), and from then on the brain fits again every REFIT_MS
from the growing recording, for as long as the camera is on. When the camera goes off or the
recording is stopped there is one last fit, and the model simply carries on.

While the lesson runs, every decision that has a fresh camera label is scored: did the radio say
what the camera said? The last LAST_N of those are the screen's "learning: 6 of 10".

This class only keeps the lesson's own state; brain/core.py asks it what to do.
"""
from __future__ import annotations

import logging
from collections import deque
from typing import Optional

REFIT_MS = 15_000   # between the end of one fit and the start of the next
LAST_N = 10         # decisions the agreement is counted over
LABEL_FRESH_MS = 1_000

log = logging.getLogger("brain")


class Lesson:
    def __init__(self):
        self.session: Optional[str] = None   # the open train recording being taught from; None = no lesson
        self.started_t: Optional[int] = None
        self.fits = 0
        self._last_fit_t = 0
        self._last = False                   # the lesson is over and its last fit is still to run
        self._own = False                    # the fit about to start was asked for by due(), not the screen
        self._recent: deque = deque(maxlen=LAST_N)

    @property
    def on(self) -> bool:
        return self.session is not None

    def train_cmd(self, now: int, open_session: Optional[str]) -> None:
        """A fit is starting. With a train recording open, that is the start of a lesson."""
        self._last_fit_t = now
        own, self._own = self._own, False
        if open_session and open_session != self.session and not own:
            self.session, self.started_t, self.fits, self._last = open_session, now, 0, False
            self._recent.clear()
            log.info("lesson: started on %s", open_session)

    def fitted(self, now: int, ok: bool) -> None:
        """A fit finished (ok False = it failed). The next one is REFIT_MS from here."""
        self._last_fit_t = now
        if self.on and ok:
            self.fits += 1
            log.info("lesson: fit %d done %.1f s after the start", self.fits, (now - self.started_t) / 1000)

    def due(self, now: int, open_session: Optional[str], cam: str, fitting: bool) -> bool:
        """True when the brain should fit again now. Call on every state tick."""
        if self.on and (open_session != self.session or cam == "off"):
            agree, of = self.agreement()
            log.info("lesson: over (%s); the radio agreed with the camera on %d of the last %d decisions",
                     "the camera is off" if cam == "off" else "the recording stopped", agree, of)
            self.session, self._last = None, True
        if fitting:
            return False
        if self._last or (self.on and cam == "on" and now - self._last_fit_t >= REFIT_MS):
            self._last_fit_t = now   # even if the fit can't start, don't ask again on every tick
            self._last, self._own = False, True
            return True
        return False

    def saw(self, now: int, pred: Optional[dict], label: Optional[dict]) -> None:
        """One fresh decision. It counts when the camera has a usable label for the same moment."""
        if not self.on or pred is None or label is None or label.get("clipped"):
            return
        if now - label.get("recv_t", now) > LABEL_FRESH_MS:
            return
        camera = (label.get("zone") or 0) if label.get("present") else 0
        radio = (pred.get("zone") or 0) if pred.get("present") else 0
        self._recent.append(camera == radio)

    def agreement(self) -> tuple:
        return sum(self._recent), len(self._recent)

    def block(self, training: Optional[dict]) -> Optional[dict]:
        """state.model.training: the running fit's block, and during a lesson the learning signal too."""
        if not self.on:
            return training
        agree, of = self.agreement()
        base = training or {"started_t": self.started_t, "progress": None, "sessions": [self.session]}
        return {**base, "lesson": {"started_t": self.started_t, "agree": agree, "of": of,
                                   "fits": self.fits, "fitting": training is not None}}
