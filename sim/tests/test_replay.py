import io
import time

from sim import fake, replay
from sim.wire import encode


def record(tmp_path, name="stand_still", seconds=1.0):
    lines = [encode(e) for e in fake.simulate(fake.load_path(name)) if e["t"] < seconds]
    f = tmp_path / "session.jsonl"
    f.write_text("\n".join(lines) + "\n\n")  # trailing blank line on purpose
    return f, lines


def test_read_gives_times_and_skips_blank_lines(tmp_path):
    f, lines = record(tmp_path)
    with open(f) as fh:
        got = list(replay.read(fh))
    assert [line for _, line in got] == lines
    assert got[0][0] == 0.0 and got[-1][0] < 1.0


def test_replay_output_is_identical_to_the_recording(tmp_path, capsys):
    f, lines = record(tmp_path, seconds=0.5)
    replay.main([str(f), "--speed", "50"])
    assert capsys.readouterr().out.splitlines() == lines


def test_replay_runs_at_real_speed(tmp_path, capsys):
    f, _ = record(tmp_path, seconds=0.5)  # last reading at about 0.47 s
    start = time.monotonic()
    replay.main([str(f)])
    assert 0.4 <= time.monotonic() - start <= 0.8


def test_timestamps_need_not_start_at_zero():
    now = [0.0]
    lines = io.StringIO('{"t":1700000000.0}\n{"t":1700000001.5}\n')
    fake.pace(replay.read(lines), out=io.StringIO(), clock=lambda: now[0],
              sleep=lambda s: now.__setitem__(0, now[0] + s))
    assert abs(now[0] - 1.5) < 1e-6
