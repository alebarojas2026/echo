"""Things the real feed gets wrong: clipped camera labels and lost messages."""
import json

from brain import features
from contracts.check import check_lines, errors
from sim import fake, send
from sim.wire import encoder


def labels(path):
    return [e for e in fake.simulate(path) if e["type"] == "label"]


def test_clipped_labels_have_no_zone_or_foot_point():
    got = labels(fake.load_path("clipped_feet"))
    clipped = [e for e in got if e["clipped"]]
    assert clipped and {round(e["t"]) for e in clipped} <= {6, 7, 8, 9}
    assert all(6 <= e["t"] < 9 for e in clipped)
    for e in clipped:
        assert (e["zone"], e["foot_m"], e["motion"], e["present"], e["persons_in_frame"]) == (None, None, None, True, 1)
    clear = [e for e in got if not e["clipped"] and e["present"]]
    assert all(e["zone"] in (1, 2) and e["foot_m"] for e in clear)


def test_clipped_while_walking_also_has_no_motion():
    path = {"duration_s": 3, "person": [{"t": 0, "x": 0.2, "y": 0.5}, {"t": 3, "x": 1.8, "y": 0.5}],
            "clipped": [{"t_on": 1, "t_off": 2}]}
    got = labels(path)
    assert {e["motion"] for e in got if e["clipped"]} == {None}
    assert {e["motion"] for e in got if not e["clipped"]} == {"moving"}


def test_clipping_needs_a_person_in_frame():
    path = {"duration_s": 4, "person": [{"t": 0, "x": 0.5, "y": 0.5}, {"t": 2, "x": None}], "clipped": [{"t_on": 1}]}
    got = labels(path)
    assert {e["clipped"] for e in got if 1 <= e["t"] < 2} == {True}
    assert {(e["clipped"], e["zone"]) for e in got if e["t"] >= 2} == {(False, 0)}


# CONTRACTS.md says a clipped label has motion null. The label schema catches up in #173; until then
# it reports exactly this for a clipped label, and nothing else may fail.
SCHEMA_LAG = {"$.motion: None is not one of ['moving', 'still']"}


def test_clipped_feed_passes_the_contract_checker():
    encode = encoder(1763149500000)
    for e in fake.simulate(fake.load_path("clipped_feet")):
        found = set(errors(json.loads(encode(e))))
        assert found <= (SCHEMA_LAG if e.get("clipped") else set()), (e["t"], found)


def test_brain_drops_windows_with_a_clipped_label():
    got = labels(fake.load_path("clipped_feet"))
    inside = [e for e in got if 7.0 <= e["t"] < 8.0]
    before = [e for e in got if 3.0 <= e["t"] < 4.0]
    assert features.window_label(inside) is None and features.window_label(before) is not None


def encoded(path, loss, seed=0):
    encode = encoder(1763149500000)
    return [line for _, line in fake.lossy(((e["t"], encode(e)) for e in fake.simulate(path)), loss, seed)]


def test_loss_drops_about_the_asked_share_and_leaves_seq_gaps():
    path = fake.load_path("empty_room")
    full, some = encoded(path, 0.0), encoded(path, 0.1)
    assert 0.07 < 1 - len(some) / len(full) < 0.13
    seqs = [json.loads(l)["seq"] for l in some]
    assert seqs == sorted(seqs) and seqs[0] == 1 and len(set(seqs)) == len(seqs)
    assert seqs[-1] - seqs[0] + 1 > len(seqs)  # gaps
    assert set(some) <= set(full)  # surviving lines are untouched
    assert encoded(path, 0.1) == some and encoded(path, 0.1, seed=1) != some


def test_checker_reports_the_gaps_as_warnings_not_failures():
    count, failures, warnings = check_lines(encoded(fake.load_path("empty_room"), 0.05))
    assert failures == [] and len(warnings) > 10


def test_cli_loss_flag(capsys):
    fake.main(["empty_room", "--fast", "--loss", "0.5", "--start-ms", "0"])
    lines = capsys.readouterr().out.splitlines()
    assert json.loads(lines[0])["type"] == "meta"
    assert 0.4 < len(lines) / (1 + 30 * 15 * 6 + 30 * 15 // 2 + 30) < 0.6


def test_send_loss_flag(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(send.UdpOut, "write", lambda self, text: sent.append(json.loads(text)))
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"name": "p", "duration_s": 2, "person": None}))
    send.main([str(f), "--speed", "100", "--loss", "0.3"])
    seqs = [m["seq"] for m in sent]
    assert seqs[0] == 1 and seqs[-1] - len(seqs) > 20
