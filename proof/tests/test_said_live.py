"""A live run counted from the arrivals the board said, as its narrator recorded them."""
import json

import pytest

from proof import render_table, said_live as S
from proof.provenance import empty_proof


def run(tmp_path, stands=3, tail_s=30, extra=(), src="live"):
    rows = [dict(v=2, type="meta", recv_t=0, src=src, session="live-run", purpose="demo")]
    end = stands * 20000 + tail_s * 1000
    rows += [dict(v=2, type="rssi", src=src, recv_t=t, link="a>b:wifi", dbm=-40) for t in range(0, end + 1, 500)]
    for i in range(stands):
        for kind, at in (("enter", 5000), ("exit", 14000)):
            rows.append(dict(v=2, type="narration", src=src, recv_t=i * 20000 + at + 3000, gen_ms=3000, text="...",
                             event_kind=kind, event_id=f"e{2 * i + (kind == 'exit')}"))
    rows += [dict(v=2, type="narration", src=src, recv_t=t + 3000, gen_ms=3000, text="...", event_kind=kind, event_id=f"x{t}")
             for t, kind in extra]
    path = tmp_path / "live-run.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in sorted(rows, key=lambda r: r["recv_t"])), encoding="utf-8")
    return path


def test_each_stand_with_an_arrival_and_a_leaving_said_is_found_and_the_tail_is_clean(tmp_path):
    r = S.count(run(tmp_path), 3, 30, "a" * 40)
    assert (r["found"], r["stands"], r["arrivals_said"], r["extra_arrivals"]) == (3, 3, 3, 0)
    assert r["held_s"] == [9.0, 9.0, 9.0] and (r["tail_arrivals"], r["tail_events"], r["empty_tail_s"]) == (0, 0, 30.0)
    text = "\n".join(S.table(r))
    assert "3 of 3 stands found; with this few trials the true rate is probably between 29% and 100%" in text
    assert "not replayed" in text and '"no arrival said", not "no false presence"' in text
    document = render_table.render("# Proof\n", empty_proof(), live=r)
    assert "## Live on the kit (the board's own decisions, not replayed)" in document
    assert document == render_table.render(document, empty_proof(), live=r)


def test_a_missed_stand_an_extra_arrival_and_an_arrival_in_the_empty_tail_all_show(tmp_path):
    assert S.count(run(tmp_path), 4, 10, "a" * 40)["found"] == 3          # the operator stood four times; three were said
    r = S.count(run(tmp_path, extra=[(70000, "enter"), (72000, "exit")]), 3, 30, "a" * 40)
    assert (r["found"], r["tail_arrivals"], r["tail_events"]) == (3, 1, 2)
    r = S.count(run(tmp_path, extra=[(17000, "enter"), (18000, "exit"), (19000, "intrusion")]), 3, 30, "a" * 40)
    assert (r["found"], r["extra_arrivals"], r["other_events_said"]) == (3, 1, ["intrusion"])


def test_a_second_sentence_for_the_same_event_is_one_event(tmp_path):
    path = run(tmp_path)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows.append(dict(next(r for r in rows if r["type"] == "narration"), text="said again"))
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    assert S.count(path, 3, 30, "a" * 40)["arrivals_said"] == 3


@pytest.mark.parametrize("fault", ["sim", "commit", "stands", "tail", "method"])
def test_what_is_not_a_live_run_with_its_build_is_refused(tmp_path, fault):
    path = run(tmp_path, src="sim" if fault == "sim" else "live")
    with pytest.raises(ValueError):
        r = S.count(path, 0 if fault == "stands" else 3, 900 if fault == "tail" else 30, "abc" if fault == "commit" else "a" * 40)
        S.table(dict(r, method="replayed") if fault == "method" else r)
        raise AssertionError("accepted")
