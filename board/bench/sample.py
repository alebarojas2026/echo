"""Samples CPU, clock, temperature and memory on the board into a CSV, then sums it up.

    python board/bench/sample.py --seconds 300 --every 2 --csv /tmp/load.csv

Linux only. Per sample: a "system" row (CPU % of all cores, MB in use, hottest thermal zone,
slowest core clock, clock cap) and a row per Radio Sight process, or any other over 5% CPU
(CPU % of one core, RSS). Throttling: over 80 C, the clock capped, or slow while busy.
"""
import argparse
import glob
import os
import time

NAMES = [("bench_brain", "bench_brain"), ("brain", "brain.main"), ("bus", "-m bus"), ("sim_send", "sim.send"),
         ("wifi_rssi", "radio.wifi_rssi"), ("hci_scan", "radio.hci_scan"), ("camwatch", "teacher.camwatch"),
         ("serve", "board/serve.py"), ("llama-server", "llama-server"), ("narrate", "narrator.narrate"),
         ("llm_time", "llm_time.py")]
HOT_C, BUSY_PCT, OTHER_PCT = 80.0, 50.0, 5.0
CPUFREQ = "/sys/devices/system/cpu/cpu[0-9]*/cpufreq/"


def read(path):
    try:
        return open(path).read()
    except OSError:
        return ""


def values(root, pattern):
    return [int(v) / 1000 for v in (read(p).strip() for p in glob.glob(root + pattern)) if v.isdigit()]


def snapshot(root=""):
    cpu = [int(x) for x in read(root + "/proc/stat").split("\n")[0].split()[1:9]]
    mem = {k: int(v.split()[0]) for k, v in
           (ln.split(":", 1) for ln in read(root + "/proc/meminfo").splitlines() if ":" in ln)}
    procs = {}
    for d in glob.glob(root + "/proc/[0-9]*"):
        stat, statm = read(d + "/stat"), read(d + "/statm")
        if stat and statm:
            f, comm = stat.rsplit(")", 1)[1].split(), stat[stat.find("(") + 1:stat.rfind(")")]
            procs[int(os.path.basename(d))] = {
                "jiffies": int(f[11]) + int(f[12]), "rss_pages": int(statm.split()[1]), "comm": comm,
                "cmd": read(d + "/cmdline").replace("\0", " ").strip() or comm}
    return {"busy": sum(cpu) - cpu[3] - cpu[4], "total": sum(cpu), "procs": procs,
            "mem_mb": (mem.get("MemTotal", 0) - mem.get("MemAvailable", 0)) / 1024,
            "temp": max(values(root, "/sys/class/thermal/thermal_zone*/temp"), default=None),
            "mhz": min(values(root, CPUFREQ + "scaling_cur_freq"), default=None),
            "cap": min(values(root, CPUFREQ + "scaling_max_freq"), default=None),
            "top": max(values(root, CPUFREQ + "cpuinfo_max_freq"), default=None)}


def rows(a, b, dt, t_s, me=None, hz=100, page_kb=4):
    """Rows between snapshots a and b: t_s, what, pid, cpu_pct, rss_mb, temp_c, mhz_min, mhz_cap."""
    sys_pct = 100.0 * (b["busy"] - a["busy"]) / max(1, b["total"] - a["total"])
    out = [[t_s, "system", "", sys_pct, b["mem_mb"], b["temp"], b["mhz"], b["cap"]]]
    for pid, p in b["procs"].items():
        if pid in a["procs"] and pid != me:
            pct = 100.0 * (p["jiffies"] - a["procs"][pid]["jiffies"]) / hz / dt
            name = next((n for n, pattern in NAMES if pattern in p["cmd"]), None)
            if name or pct > OTHER_PCT:
                out.append([t_s, name or p["comm"], pid, pct, p["rss_pages"] * page_kb / 1024] + [None] * 3)
    return out


def summary(table, top=None):
    """Summary lines, and whether anything looked like throttling."""
    sysrows = [r for r in table if r[1] == "system"]
    if not sysrows:
        return ["no samples"], False
    cpu, temps = sorted(r[3] for r in sysrows), [r[5] for r in sysrows if r[5] is not None]
    mhz = [r[6] for r in sysrows if r[6] is not None]
    lines = [f"{len(sysrows)} samples over {sysrows[-1][0]:.0f} s",
             f"system: CPU avg {sum(cpu) / len(cpu):.0f}%, p95 {_p95(cpu):.0f}% of all cores; "
             f"memory in use max {max(r[4] for r in sysrows):.0f} MB; temp max {max(temps, default='?')} C; "
             f"slowest core {min(mhz, default='?')}-{max(mhz, default='?')} MHz (CPU max {top or '?'})",
             f"{'process':<16}{'cpu avg %':>10}{'cpu p95 %':>10}{'rss max MB':>11}"]
    procs = {n: [r for r in table if r[1] == n] for n in {r[1] for r in table} - {"system"}}
    for name, rs in sorted(procs.items(), key=lambda kv: -sum(r[3] for r in kv[1])):
        pct = sorted(r[3] for r in rs)
        lines.append(f"{name:<16}{sum(pct) / len(sysrows):>10.1f}{_p95(pct):>10.1f}{max(r[4] for r in rs):>11.0f}")
    flags = [f"{what} in {n} samples" for what, n in (
        (f"over {HOT_C:.0f} C", sum(t > HOT_C for t in temps)),
        (f"clock capped under {top} MHz", sum(top is not None and (r[7] or top) < top for r in sysrows)),
        ("a core under its cap while busy",
         sum(r[3] > BUSY_PCT and None not in (r[6], r[7]) and r[6] < r[7] for r in sysrows))) if n]
    lines.append("THROTTLING: " + "; ".join(flags) if flags else "throttling: none seen")
    return lines, bool(flags)


def _p95(vals):
    return vals[min(len(vals) - 1, int(0.95 * len(vals)))]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seconds", type=float, default=300)
    ap.add_argument("--every", type=float, default=2)
    ap.add_argument("--csv", required=True)
    a = ap.parse_args(argv)
    hz, page_kb = os.sysconf("SC_CLK_TCK"), os.sysconf("SC_PAGE_SIZE") // 1024
    table, start = [], time.monotonic()
    prev, prev_t = snapshot(), start
    with open(a.csv, "w") as f:
        f.write("t_s,what,pid,cpu_pct,rss_mb,temp_c,mhz_min,mhz_cap\n")
        while time.monotonic() - start < a.seconds:
            time.sleep(max(0.0, prev_t + a.every - time.monotonic()))
            snap, now = snapshot(), time.monotonic()
            new = rows(prev, snap, now - prev_t, round(now - start, 1), os.getpid(), hz, page_kb)
            f.writelines(",".join("" if v is None else f"{v:.1f}" if isinstance(v, float) else str(v)
                                  for v in r) + "\n" for r in new)
            f.flush()
            table, prev, prev_t = table + new, snap, now
    print("\n".join(summary(table, prev["top"])[0]), flush=True)


if __name__ == "__main__":
    main()
