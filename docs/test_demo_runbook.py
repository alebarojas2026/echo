import unittest
from pathlib import Path

from beats import BEATS, CORE


RUNBOOK = Path(__file__).with_name("demo-runbook.md")


class DemoRunbookTest(unittest.TestCase):
    def test_judge_day_preparation_and_freeze_are_explicit(self):
        steps = ("Power up", "Set the board's clock", "--before-lesson", "commit the deploy printed", "Capture the empty baseline", "morning lesson", "outside the team", "real local model", "Copy what the board learned")
        positions = [self.text.index(step) for step in steps]
        self.assertEqual(positions, sorted(positions))
        for phrase in ("**From Sunday 9:30 AM", "**Before any restart", "board/deploy.sh <last-good-tag>", "board/push-web.sh --back", "pending #678 and #679"):
            self.assertIn(phrase, self.text)

    @classmethod
    def setUpClass(cls):
        cls.text = RUNBOOK.read_text(encoding="utf-8")
        cls.lower = cls.text.lower()

    def test_required_stages_are_present(self):
        for heading in (
            "At the desk",
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

    def test_at_the_desk_assigns_roles_and_failure_words(self):
        at_desk = self.lower.split("## at the desk", 1)[1].split("## preflight", 1)[0]
        for role in ("talker", "operator", "hardware", "spotter"):
            self.assertIn(f"| {role} |", at_desk)
        for phrase in (
            "that's the honest failure. a radio link dropped",
            "the screen lost the board's feed",
            "the lesson needs a moment with nobody in view",
            "we'll use the lesson it learned this morning",
            "the language model on this board is tiny",
            "this is a recording of the real board from this morning",
        ):
            self.assertIn(phrase, at_desk)
        self.assertIn("at least two people at the desk", at_desk)
        self.assertNotIn("not ready", self.lower)

    def test_contract_v2_failure_states_are_distinct(self):
        self.assertIn("### `NO DATA`", self.text)
        self.assertIn("### `SENSOR BLIND`", self.text)
        self.assertIn("last state is stale", self.lower)
        self.assertIn("required classifier link is unhealthy", self.lower)

    def test_primary_beats_are_in_order(self):
        beats = [f"**{beat.lower()}:**" for beat in BEATS]
        positions = [self.lower.index(beat) for beat in beats]
        self.assertEqual(positions, sorted(positions))

    def test_found_you_names_qualcomm_and_on_device(self):
        found = self.lower.split("**found you:**", 1)[1].split("**teach the room:**", 1)[0]
        for phrase in (
            "arduino uno q",
            "qualcomm dragonwing",
            "entirely on device",
            "board has no internet",
            "laptop is only a screen",
        ):
            self.assertIn(phrase, found)

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

    def test_dead_zone_beat_waits_for_the_live_wifi_drop(self):
        desk = self.lower.split("## three-minute desk round", 1)[1].split(
            "## camera-unplug proof", 1
        )[0]
        self.assertIn("pi5>pi5b:wifi", finalist)
        self.assertIn("configured drop threshold", finalist)
        self.assertIn("stop this beat if it still targets the short desk link", finalist)

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
            "three devices for one spot",
            "pi b about a metre away at desk height",
            "wi-fi from pi a to pi b is the main presence sensor",
            "lean aside",
            "step up to the desk",
            "baseline {keep_model: true}",
            "camera unplugged",
            "keeps the trained model",
        ):
            self.assertIn(phrase, self.lower)


if __name__ == "__main__":
    unittest.main()
