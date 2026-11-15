import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from board.bench import bench_brain, llm_time, sample


def test_bench_brain_times_every_step_and_reaches_the_advisor():
    res = bench_brain.run(seconds=60, fast=True, walkers=1, out=(lines := []).append)
    assert res["ticks"] == 600 and set(res["steps"]) == set(bench_brain.STEPS) | {"tick"}
    assert all(0 <= s["p50"] <= s["p95"] <= s["max"] for s in res["steps"].values())
    # A person, then the tray at the layout's T1: every part of the hot path gets real work.
    assert res["pred"] > 500 and res["objects"] > 0
    # On one spot the advisor is still called and timed, and gives no advice: the router is cabled and does not move.
    one_spot = len(json.loads((bench_brain.REPO / "radio" / "nodes.json").read_text(encoding="utf-8"))["zones"]) == 1
    assert res["advice"] == 0 if one_spot else res["advice"] > 0
    assert any(line.startswith("tick (all)") for line in lines)


class FakeLlama(BaseHTTPRequestHandler):
    bodies = []

    def do_POST(self):
        FakeLlama.bodies.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        # The model's sentence: the first timed event's own facts, so its zone and its number are ones
        # this layout has (a number that isn't in the facts would be thrown out as made up).
        said = llm_time.narrate.template(*llm_time.EVENTS[0])
        body = json.dumps({"choices": [{"message": {"content": said}}],
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
    assert (r["prompt_n"], r["prompt_tok_s"], r["gen_n"], r["gen_tok_s"], r["problem"]) == (31, 80.5, 9, 9.25, None)
    warm, sent = FakeLlama.bodies   # the warm-up goes first and isn't counted
    assert sent["cache_prompt"] and "alert_on" in sent["messages"][-1]["content"]
    assert [llm_time.verdict([dict(r, wall_ms=w)])[0] for w in (8000, 8001, None)] == [True, False, False]


def test_llm_time_asks_about_zones_the_layout_has():
    zones = llm_time.narrate.ZONES   # from radio/nodes.json
    assert zones and all(info.get("zone", min(zones)) in zones for _, info in llm_time.EVENTS)
    (kind, info), limits = llm_time.EVENTS[0], [limit for _, limit in zones.values() if limit]
    assert kind == "alert_on" and zones[info["zone"]][1] == min(limits)
    assert f"{min(limits)} seconds" in llm_time.narrate.template(kind, info)   # the limit is in the prompt
    square = {1: ("Bed", 60), 2: ("Chair", None), 3: ("Hall", None), 4: ("Bathroom", 10)}
    assert [i.get("zone") for _, i in llm_time.events(square)] == [4, 2, 3, None, 1]
    strip = {1: ("Left", 10), 2: ("Right", 10)}
    assert [i.get("zone") for _, i in llm_time.events(strip)] == [1, 2, 1, None, 1]
    assert [i for _, i in llm_time.events({})] == [{}, {}, {}, {"node": "pi5"}, {}]


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
    assert llama[1:5] == ["llama-server", 42, pytest.approx(75.0), pytest.approx(110000 * 4 / 1024)]
    lines, throttled = sample.summary([system, llama], 2016.0)
    assert throttled and "over 80 C in 1" in lines[-1] and "capped under 2016.0 MHz" in lines[-1]
    assert any(line.startswith("llama-server") for line in lines)
    assert not sample.summary([[2.0, "system", "", 90.0, 900.0, 55.0, 2016.0, 2016.0]], 2016.0)[1]
