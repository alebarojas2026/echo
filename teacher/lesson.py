"""What a camera lesson must contain, and the words that guide a person through it.

A lesson that only ever shows the camera a person teaches the radio a ghost: the model has never
seen what the links look like with nobody there, so it reports someone on an empty strip. So the
lesson starts empty, has the person step right out of view once in the middle, and is not
finished (no train) until the camera has really seen nobody for a few seconds.

"Empty" means the camera sees nobody at all (state.teacher present false). Someone standing back
is not empty: the desk view drops those frames (state.teacher is null), see teacher/DESK.md.
"""

EMPTY_S = 6        # nobody in view at the start
OUT_S = 5          # the step out of view in the middle
MIN_EMPTY_S = 3.0  # the shortest stretch of nobody that counts
EMPTY, LEFT, RIGHT = "empty", "left", "right"
WORDS = {
    (EMPTY, True): "Stay out of the camera's view: the lesson starts with the space empty.",
    (EMPTY, False): "Step right out of the camera's view and wait.",
    (LEFT, True): "Step in on your LEFT and stand there.",
    (LEFT, False): "Step to your LEFT and stand there.",
    (RIGHT, True): "Step in on your RIGHT and stand there.",
    (RIGHT, False): "Step to your RIGHT and stand there.",
}
NO_EMPTY = ("This lesson has no empty time yet, so it would teach the radio that someone is always here. "
            "Step right out of the camera's view for a few seconds; train is sent as soon as the camera has seen nobody.")


def script(teach_s: float, step_s: float) -> list:
    """[(from s, what, words)] up to teach_s: empty, left and right, a step out in the middle, then
    left and right again. A lesson too short for the step out still starts empty."""
    empty = min(EMPTY_S, teach_s / 3)
    with_out = teach_s >= empty + OUT_S + 4 * step_s
    out_at = empty + 2 * step_s if with_out else None
    steps, t, side, entering = [(0.0, EMPTY)], empty, 0, True
    while t < teach_s:
        if out_at is not None and t >= out_at:
            steps.append((t, EMPTY))
            t, out_at, entering = t + OUT_S, None, True
            continue
        steps.append((t, (LEFT, RIGHT)[side % 2], entering))
        t, side, entering = t + step_s, side + 1, False
    return [(s[0], s[1], WORDS[(s[1], s[2] if len(s) == 3 else s[0] == 0)]) for s in steps]


class EmptyTime:
    """Feed it what the camera says, once per state; it knows whether the lesson has empty time."""

    def __init__(self, min_s: float = MIN_EMPTY_S):
        self.min_s, self.since, self.stretches, self._counted = min_s, None, 0, False

    def saw(self, s: float, cam: str, teacher) -> None:
        """s: seconds since the lesson started. teacher: state.teacher (None when the label was dropped)."""
        empty = cam == "on" and isinstance(teacher, dict) and not teacher.get("present")
        if not empty:
            self.since, self._counted = None, False
            return
        if self.since is None:
            self.since = s
        if not self._counted and s - self.since >= self.min_s:
            self.stretches, self._counted = self.stretches + 1, True

    def ok(self) -> bool:
        return self.stretches > 0

    def summary(self) -> str:
        if not self.stretches:
            return "empty time: none (the lesson was not finished: no train was sent)"
        return f"empty time: {self.stretches} stretch{'es' if self.stretches > 1 else ''} of {self.min_s:g} s or more"
