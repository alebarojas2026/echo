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
            "Three-minute desk round",
            "Camera-unplug proof",
            "Five-minute finalist round",
            "Proof check",
            "Recovery",
            "After the demo",
        ):
            self.assertIn(f"## {heading}", self.text)

    def test_contract_v2_failure_states_are_distinct(self):
        self.assertIn("### `NO DATA`", self.text)
        self.assertIn("### `SENSOR BLIND`", self.text)
        self.assertIn("last state is stale", self.lower)
        self.assertIn("required classifier link is unhealthy", self.lower)

    def test_primary_beats_are_in_order(self):
        beats = (
            "**found you:**",
            "**teach the room:**",
            "**camera unplug:**",
            "**still follows:**",
            "**arm the space:**",
            "**intrusion alert:**",
            "**ask the room:**",
            "**proof:**",
        )
        positions = [self.lower.index(beat) for beat in beats]
        self.assertEqual(positions, sorted(positions))

    def test_demo_includes_privacy_and_proof_moments(self):
        for phrase in (
            "unplug the camera",
            "teacher` becomes null",
            "lesson time: __ s",
            "images stored: __",
            "bytes sent outside local network: __",
            "go directly to **proof**",
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
            "radio/nodes.json",
            "do not copy files or bundles",
        ):
            self.assertIn(phrase, self.lower)

    def test_finalist_advice_waits_for_the_live_wifi_drop(self):
        finalist = self.lower.split("## five-minute finalist round", 1)[1].split(
            "## if asked", 1
        )[0]
        self.assertIn("pi5>unoq:wifi", finalist)
        self.assertIn("drop_db` of at least `3 db`", finalist)
        self.assertIn("advice does not appear without that live drop", finalist)

    def test_finish_order_clears_optional_hardware_before_reset(self):
        steps = (
            "remove it",
            "object marker and static change to clear",
            "return the pi to its home spot",
            "send `router_home`",
            "everyone steps away from the sensing area and its edge",
            "stays out until a prediction returns or `baseline_done` appears",
            "send `reset`",
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
            "template recap",
        ):
            self.assertIn(phrase, self.lower)

    def test_desk_layout_and_same_layout_recovery_are_explicit(self):
        for phrase in (
            "power pi b",
            "three `25 cm` boxes",
            "two cardboard arms",
            "string knotted at `0`, `0.5`, `0.8`, `1.1`, and `1.6 m`",
            "step up to the desk",
            "baseline {keep_model: true}",
            "camera unplugged",
            "keeps the trained model",
        ):
            self.assertIn(phrase, self.lower)


if __name__ == "__main__":
    unittest.main()
