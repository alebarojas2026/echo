"""brain.linkrank on synthetic blocks: a link is "clear" only when a person changes it by more than
it changes by itself between two empty blocks."""
import json
import random

import pytest

from brain import linkrank as LR

WIFI, BLE, SLOW, SIDE = "pi5>pi5b:wifi", "east>unoq:ble", "pi5>pi5b:ble", "west>unoq:ble"


def link(rng, level, noise, hz, seconds=20.0, t0=0.0):
    """Whole-dBm readings like a radio gives: `hz` a second around `level` with `noise` dB of wobble,
    part of it slow (a new offset every 0.5 s), so the 0.5 s means move as they do on the kit."""
    out, t, slow = [], t0, 0.0
    while t < t0 + seconds * 1000:
        if int(t // 500) != int((t - 1000 / hz) // 500):
            slow = rng.gauss(0, noise * 0.6)
        out.append((t, round(level + slow + rng.gauss(0, noise * 0.8))))
        t += 1000 / hz
    return out


def block(rng, wifi=-47, ble=-64, slow=-55, side=-50, ble_noise=3.0):
    return {WIFI: link(rng, wifi, 0.4, 24), BLE: link(rng, ble, ble_noise, 10),
            SLOW: link(rng, slow, 1.2, 2), SIDE: link(rng, side, 0.5, 13)}


def by_link(result):
    return {r["link"]: r for r in result["rows"]}


def test_a_quiet_link_the_person_crosses_is_clear_and_ranked_first():
    rng = random.Random(1)
    result = LR.rank([("empty", block(rng)), ("person", block(rng, wifi=-51)), ("empty", block(rng))])
    rows = by_link(result)
    assert result["rows"][0]["link"] == WIFI
    assert rows[WIFI]["verdict"] == "clear"
    assert rows[WIFI]["change"] == pytest.approx(-4, abs=0.6)
    assert rows[WIFI]["apart"] > 0.9
    assert rows[BLE]["verdict"] == "no signal"
    assert "Detection is carried by " + WIFI in LR.summary(result)


def test_a_change_no_bigger_than_the_drift_between_two_empty_blocks_is_no_signal():
    """3 dB with a person, on a link that reads 3 dB apart in two empty blocks: nothing."""
    rng = random.Random(2)
    result = LR.rank([("empty", block(rng, ble=-62, ble_noise=1.0)),
                      ("person", block(rng, ble=-66.5, ble_noise=1.0)),
                      ("empty", block(rng, ble=-65, ble_noise=1.0))])
    row = by_link(result)[BLE]
    assert row["floor"] == pytest.approx(3, abs=0.8)
    assert row["x"] < 1.3
    assert row["verdict"] == "no signal"
    assert "No link tells a person from an empty area" in LR.summary(result)


def test_the_same_change_on_a_link_that_holds_still_between_empties_is_clear():
    rng = random.Random(3)
    result = LR.rank([("empty", block(rng, ble_noise=1.0)), ("person", block(rng, ble=-67.5, ble_noise=1.0)),
                      ("empty", block(rng, ble_noise=1.0))])
    assert by_link(result)[BLE]["verdict"] == "clear"


def test_a_small_change_on_a_noisy_link_is_never_clear():
    rng = random.Random(4)
    result = LR.rank([("empty", block(rng)), ("person", block(rng, ble=-66)), ("empty", block(rng))])
    assert by_link(result)[BLE]["verdict"] in ("weak", "no signal")


def test_movement_shows_in_the_spread():
    rng = random.Random(5)
    walking = block(rng)
    walking[WIFI] = link(rng, -47, 2.5, 24)   # same level, much more wobble
    result = LR.rank([("empty", block(rng)), ("person", walking), ("empty", block(rng))])
    row = by_link(result)[WIFI]
    assert (row["verdict"], row["by"]) == ("clear", "spread")
    assert "in the spread" in LR.table(result)


def test_left_and_right_are_told_apart_by_a_link_only_one_of_them_crosses():
    rng = random.Random(6)
    result = LR.rank([("empty", block(rng)), ("left", block(rng, wifi=-50, side=-56)), ("empty", block(rng)),
                      ("right", block(rng, wifi=-50)), ("empty", block(rng))])
    assert result["tags"] == ["left", "right"]
    told = dict(LR.sides(result))
    assert SIDE in told and told[SIDE] == pytest.approx(-6, abs=0.8)
    assert WIFI not in told   # it sees both, the same
    assert "Left and right can be told apart on " + SIDE in LR.summary(result)
    assert by_link(result)[SIDE]["place"] == "left"
    lines = LR.table(result).splitlines()
    assert any(ln.startswith(SIDE) and ln.endswith("clear at left") for ln in lines)
    assert any(ln.startswith(WIFI) and ln.endswith("clear at left, right") for ln in lines)   # both cross it


def test_left_and_right_that_read_the_same_cannot_be_told_apart():
    rng = random.Random(7)
    result = LR.rank([("empty", block(rng)), ("left", block(rng, wifi=-50)), ("right", block(rng, wifi=-50)),
                      ("empty", block(rng))])
    assert LR.sides(result) == []
    assert "cannot be told apart" in LR.summary(result)


def test_without_left_and_right_it_says_they_were_not_tested():
    rng = random.Random(8)
    result = LR.rank([("empty", block(rng)), ("person", block(rng)), ("empty", block(rng))])
    assert "was not tested" in LR.summary(result)


def test_one_empty_block_takes_the_floor_from_its_halves_and_says_so():
    rng = random.Random(9)
    result = LR.rank([("empty", block(rng)), ("person", block(rng, wifi=-51))])
    assert result["one_empty"] and by_link(result)[WIFI]["verdict"] == "clear"
    assert "Only one empty block" in LR.summary(result)


def test_a_link_with_a_handful_of_readings_is_not_judged():
    rng = random.Random(10)
    thin = block(rng)
    thin[SLOW] = thin[SLOW][:5]
    gone = block(rng)
    del gone[BLE]
    result = LR.rank([("empty", block(rng)), ("person", thin), ("empty", gone)])
    rows = by_link(result)
    assert rows[SLOW]["verdict"] == rows[BLE]["verdict"] == "too few readings"
    assert result["rows"][-1]["verdict"] == "too few readings"
    assert "__" in LR.table(result)


def test_it_needs_an_empty_block_and_a_person_block():
    rng = random.Random(11)
    with pytest.raises(ValueError, match="at least one empty block"):
        LR.rank([("empty", block(rng)), ("empty", block(rng))])


def write(path, by):
    lines = [json.dumps({"v": 2, "type": "meta", "session": path.stem})]
    lines += [json.dumps({"v": 2, "type": "rssi", "link": k, "recv_t": t, "t": t + 400000, "dbm": d})
              for k, pts in by.items() for t, d in pts]
    path.write_text("\n".join(lines + ["not json"]), encoding="utf-8")


def test_the_command_reads_session_ids_and_paths(tmp_path, capsys):
    rng = random.Random(12)
    write(tmp_path / "e1.jsonl", block(rng))
    write(tmp_path / "p.jsonl", block(rng, wifi=-52))
    write(tmp_path / "e2.jsonl", block(rng))
    LR.main(["empty=e1", f"Person={tmp_path / 'p.jsonl'}", "empty=e2", "--sessions", str(tmp_path)])
    out = capsys.readouterr().out
    assert out.splitlines()[0].split()[:3] == ["link", "/s", "empty"]
    assert out.splitlines()[1].startswith(WIFI) and "clear" in out.splitlines()[1]
    assert "Detection is carried by" in out


@pytest.mark.parametrize("spec, says", [("empty", "tag=session"), ("empty=nope", "no such file")])
def test_a_bad_block_is_refused_in_words(tmp_path, spec, says):
    with pytest.raises(SystemExit, match=says):
        LR.main([spec, "person=x", "--sessions", str(tmp_path)])


def test_capture_records_one_block_per_tag_and_refuses_while_the_bus_records(monkeypatch):
    from radio import link_stats

    done, asked = [], []
    monkeypatch.setattr(link_stats, "open_recording", lambda: None)
    monkeypatch.setattr(link_stats, "capture", lambda session, seconds: done.append((session, seconds)))
    specs = LR.record(["empty", "left"], 20, ask=asked.append, say=lambda _: None)
    assert [s.split("=")[0] for s in specs] == ["empty", "left"]
    assert [d[0] for d in done] == [s.split("=")[1] for s in specs] and done[0][1] == 20
    assert "nobody" in asked[0] and "left" in asked[1]
    monkeypatch.setattr(link_stats, "open_recording", lambda: "s9")
    with pytest.raises(ValueError, match="the bus is recording s9"):
        LR.record(["empty"], 20, ask=asked.append)
