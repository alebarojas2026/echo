import unittest
from pathlib import Path


RUNBOOK = Path(__file__).with_name("demo-runbook.md")


class DemoRunbookTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = RUNBOOK.read_text(encoding="utf-8")
        cls.lower = cls.text.lower()

    def test_required_stages_are_present(self):
        for heading in (
            "Preflight",
            "Baseline and training",
            "Camera-unplug proof",
            "Live demo sequence",
            "Proof check",
            "Recovery",
            "After the demo",
        ):
            self.assertIn(f"## {heading}", self.text)

    def test_contract_v2_failure_states_are_distinct(self):
        self.assertIn("### `NO DATA`", self.text)
        self.assertIn("### `SENSOR BLIND`", self.text)
        self.assertIn("last state is stale", self.lower)
        self.assertIn("classifier link is unhealthy", self.lower)

    def test_demo_includes_privacy_and_proof_moments(self):
        for phrase in (
            "unplug the camera",
            "teacher` becomes null",
            "checkin-toast",
            "advice-text",
            "router_moved",
            "router_home",
            "no-movement alert",
            "json `null` must render as `__`",
        ):
            self.assertIn(phrase, self.lower)

    def test_preflight_uses_the_live_laptop_path(self):
        for phrase in (
            "ask alexander to run",
            "sudo bash pi/eth.sh",
            "sudo bash board/eth.sh",
            "sudo bash pi/ap.sh",
            "sudo bash radio/wifi_join.sh",
            "join the demo laptop",
            "http://192.168.77.2:8080/?src=ws",
            "ws://192.168.77.2:8765/ws",
            "do not copy files or bundles",
        ):
            self.assertIn(phrase, self.lower)

    def test_advice_waits_for_the_live_wifi_drop(self):
        advice = self.lower.split("**router advice:**", 1)[1].split(
            "**camera unplug:**", 1
        )[0]
        self.assertIn("pi5>unoq:wifi", advice)
        self.assertIn("drop_db` of at least `3 db`", advice)
        self.assertIn("advice does not appear without that live drop", advice)

    def test_finish_order_clears_tray_before_router_home(self):
        steps = (
            "remove the tray",
            "object marker and static change clear",
            "return the pi to `s-home`",
            "send `router_home`",
            "wait until prediction resumes",
            "send `reset`",
            "end-of-demo recap appears",
        )
        positions = [self.lower.index(step) for step in steps]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("alexander handles the tray and pi", self.lower)

    def test_narrator_warmup_never_blocks_the_demo(self):
        for phrase in (
            "warm its local model in the background",
            "the template path remains available",
            "warms its normal sentence prompt again in the background after the recap",
            "do not hold the next judge for that warmup",
            "fact-based template recap",
        ):
            self.assertIn(phrase, self.lower)

if __name__ == "__main__":
    unittest.main()
