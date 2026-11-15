"""The presence line's on and off levels, through the whole brain on a feed (cold: no model, no lesson).

Made-up readings shaped like the kit's Wi-Fi line (25 a second, about 0.4 dB of wobble): they show the
rule holds at those rates, and say nothing about how well the real desk works.

One thing these tests have to step around, and it is worth knowing: a drop between object_db and
object_max_db (3 to 10 dB) that stays steady for object_hold_s (3 s) is called a thing left in the line,
not a person. So a level between on_db and object_max_db is read here inside its first 2.5 s only.
"""
from brain.core import OBJECT_HOLD_S
from brain.tests.gatefeed import GATE
from brain.tests.test_gate import cold_kit

LINE = GATE["presence"]["line"]
ON_DB, OFF_DB = GATE["presence"]["on_db"], GATE["presence"]["off_db"]
SOON = (1500, 2500)      # after the 1 s median has caught up, before the object rule's 3 s


def stand(kit, db, seconds=2.6, window=SOON):
    """Somebody takes `db` off the presence line. Returns the decisions (present, kind) inside `window` ms."""
    kit.feed.drop[LINE] = db
    start, rows, _ = kit.play([(seconds, "still")])
    return [(s["pred"]["present"], s["pred"]["kind"]) for t, s in rows if window[0] <= t - start <= window[1]]


def present(decisions):
    return [p for p, _ in decisions]


def test_the_edges_under_on_never_raises_over_on_does_between_holds_under_off_lets_go():
    kit = cold_kit(seed=31)
    assert ON_DB - OFF_DB >= 2 and OBJECT_HOLD_S > SOON[1] / 1000    # a gap to hold in; read before the object rule
    assert not any(present(stand(kit, ON_DB - 1.5)))                 # under the on level: not raised
    assert all(present(stand(kit, ON_DB + 1.5)))                     # over it: raised
    assert all(present(stand(kit, (ON_DB + OFF_DB) / 2)))            # back between the two levels: it holds
    assert not any(present(stand(kit, OFF_DB - 1.5)))                # under the off level: it lets go
    assert all(s["pred"] is not None for _, s in kit.rows[-100:])


def test_between_the_levels_alone_never_raises_it():
    kit = cold_kit(seed=32)
    said = stand(kit, (ON_DB + OFF_DB) / 2, seconds=10, window=(1500, 10_000))
    assert not any(present(said))                                    # holding needs somebody to have been there


def test_a_person_sized_drop_is_a_person_for_as_long_as_they_stand():
    kit = cold_kit(seed=34)
    said = stand(kit, 18.0, seconds=30, window=(1500, 30_000))       # 11 to 24 dB on the kit
    assert set(said) == {(True, "person")}


def test_an_empty_minute_with_dips_of_0_9_db_on_the_line_never_says_present():
    """The largest dip the empty Wi-Fi line showed on the kit was 0.9 dB (issue #789)."""
    kit = cold_kit(seed=33)
    kit.feed.drop = {LINE: 0.9}                      # only the presence line dips; no Bluetooth line moves
    says, events = [], []
    for _ in range(8):                               # 8 dips of 1 s in a minute
        for seconds, who in ((6.5, "nobody"), (1.0, "still")):
            _, rows, ev = kit.play([(seconds, who)])
            says += [(s["pred"]["present"], s["pred"]["kind"]) for _, s in rows]
            events += [e["kind"] for _, e in ev]
    assert len(says) >= 550 and set(says) == {(False, "none")}
    assert not {"enter", "intrusion", "passed_by", "object_on"} & set(events)
