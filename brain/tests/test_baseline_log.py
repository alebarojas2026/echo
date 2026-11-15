"""The log names what a baseline is waiting for."""
from brain.core import Brain
from brain.tests.simdata import sim_to_v2
from brain.tests.test_core import baseline_feed

def test_the_log_says_what_a_baseline_is_waiting_for(caplog):
    import logging
    caplog.set_level(logging.INFO, logger="brain")
    brain = Brain()

    def east_pi5_never_reports(m):
        return None if m.get("link") == "east>pi5:ble" else m

    baseline_feed(brain, edit=east_pi5_never_reports)
    assert brain.capture is not None                       # still waiting, as the contract wants
    said = [r.getMessage() for r in caplog.records if "baseline" in r.getMessage()]
    assert "baseline is waiting: no readings in the last 3 s from east>pi5:ble" in said
    assert len(said) < 10                                  # once per reason, not once per message
    caplog.clear()
    for m in sim_to_v2("empty_room", seed=2, t0=brain.feed_t + 100):   # every link reports: it goes through
        brain.on_message(m)
    said = [r.getMessage() for r in caplog.records if "baseline" in r.getMessage()]
    assert brain.capture is None and "baseline: capturing 20 s" in said
