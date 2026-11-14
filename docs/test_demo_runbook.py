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

if __name__ == "__main__":
    unittest.main()
