import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from board.bench import bench_brain, llm_time, sample


def test_bench_brain_times_every_step_and_reaches_the_advisor():
    res = bench_brain.run(seconds=60, fast=True, walkers=1, out=(lines := []).append)
    assert res["ticks"] == 600 and set(res["steps"]) == set(bench_brain.STEPS) | {"tick"}
    assert all(0 <= s["p50"] <= s["p95"] <= s["max"] for s in res["steps"].values())
    # A person, then the tray at T1: every part of the hot path gets real work.
    assert res["pred"] > 500 and res["objects"] > 0 and res["advice"] > 0
    assert any(line.startswith("tick (all)") for line in lines)


class FakeLlama(BaseHTTPRequestHandler):
    bodies = []

    def do_POST(self):
        FakeLlama.bodies.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        body = json.dumps({"choices": [{"message": {"content": "Someone stepped into zone 4."}}],
                           "timings": {"prompt_n": 31, "prompt_per_second": 80.5,
                                       "predicted_n": 9, "predicted_per_second": 9.25}}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_llm_time_sends_the_narrator_prompt_and_reads_the_timings():
    server = HTTPServer(("127.0.0.1", 0), FakeLlama)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        (r,) = llm_time.run(f"http://127.0.0.1:{server.server_port}", out=lambda s: None)
    finally:
        server.shutdown()
    assert (r["prompt_n"], r["prompt_tok_s"], r["gen_n"], r["gen_tok_s"]) == (31, 80.5, 9, 9.25)
    assert r["problem"] is None   # the narrator would put this sentence on screen
    warm, sent = FakeLlama.bodies   # the warm-up goes first and isn't counted
    assert sent["cache_prompt"] and "alert_on" in sent["messages"][-1]["content"]
    assert [llm_time.verdict([dict(r, wall_ms=w)])[0] for w in (8000, 8001, None)] == [True, False, False]


def fake_board(root, busy, idle, llama_jiffies, temp_mc, khz):
    files = {"proc/stat": f"cpu  {busy} 0 0 {idle} 0 0 0 0 0 0\n",
             "proc/meminfo": "MemTotal:  3900000 kB\nMemAvailable: 1852000 kB\n",
             "proc/42/stat": f"42 (llama-server) S 1 1 1 0 -1 0 0 0 0 0 {llama_jiffies} 0 0 0 20 10\n",
             "proc/42/statm": "200000 110000 0 0 0 0 0\n",
             "proc/42/cmdline": "/opt/rs/llama.cpp/build/bin/llama-server\0--threads\0002\0",
             "sys/class/thermal/thermal_zone0/temp": f"{temp_mc}\n"}
    for d in ("sys/devices/system/cpu/cpu0/cpufreq/", "sys/devices/system/cpu/cpu1/cpufreq/"):
        files.update({d + "scaling_cur_freq": khz, d + "scaling_max_freq": khz, d + "cpuinfo_max_freq": "2016000"})
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(str(text))
    return sample.snapshot(str(root))


def test_sample_reads_proc_and_sys_and_flags_throttling(tmp_path):
    a = fake_board(tmp_path, 1000, 1000, 100, 60000, 2016000)
    b = fake_board(tmp_path, 1600, 1200, 250, 85000, 1401000)   # 75% busy, hot, capped
    system, llama = sample.rows(a, b, dt=2.0, t_s=2.0, hz=100, page_kb=4)
    assert system[1] == "system" and system[3] == pytest.approx(75.0)
    assert system[4] == pytest.approx((3900000 - 1852000) / 1024)
    assert system[5:] == [85.0, 1401.0, 1401.0] and b["top"] == 2016.0
    assert llama[1:4] == ["llama-server", 42, pytest.approx(75.0)]   # 150 jiffies in 2 s
    assert llama[4] == pytest.approx(110000 * 4 / 1024)
    lines, throttled = sample.summary([system, llama], 2016.0)
    assert throttled and "over 80 C in 1" in lines[-1] and "capped under 2016.0 MHz" in lines[-1]
    assert any(line.startswith("llama-server") for line in lines)
    assert not sample.summary([[2.0, "system", "", 90.0, 900.0, 55.0, 2016.0, 2016.0]], 2016.0)[1]
