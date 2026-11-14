"""The scripted deployment has every part the scoring needs (SIMULATED data)."""
from lab import protocol, rf


def test_plan_has_the_demo_parts_in_order():
    sc, plan = protocol.build(0, rf.Env(), smoke=True)
    cmds = [c for _, c, _ in plan["cmds"]]
    assert cmds[0] == "baseline" and "train" in cmds
    assert cmds.index("train") > cmds.index("record_stop")
    for part in ("heldout", "tour", "walk", "alert4", "wave", "still", "tray_empty", "tray_still", "outage"):
        assert plan["spans"].get(part), part
    assert plan["spans"]["alert4"][0][1] <= plan["spans"]["wave"][0][0]
    assert plan["live0"] < plan["t_tray"] < plan["live1"] <= sc.t + 1e-6


def test_best_spots_follow_the_tray():
    assert protocol.best_spots((1.0, 0.2)) == ["S-E30", "S-W30"]       # centred: either works
    assert protocol.best_spots((1.12, 0.3)) == ["S-W30"]               # east of the line: go west
    assert protocol.best_spots((0.88, 0.3)) == ["S-E30"]
