import re
import unittest
from pathlib import Path


PITCH = Path(__file__).with_name("pitch.md")
BEATS = (
    "found you",
    "teach the room",
    "camera unplug",
    "still follows",
    "arm the space",
    "intrusion alert",
    "ask the room",
    "proof",
)


class PitchDocTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = PITCH.read_text(encoding="utf-8")
        cls.lower = cls.text.lower()
        cls.spoken = " ".join(
            line.removeprefix("> ")
            for line in cls.text.splitlines()
            if line.startswith("> ")
        )
        cls.spoken_lower = cls.spoken.lower()

    def test_spoken_script_fits_desk_round(self):
        words = re.findall(r"\b[\w'-]+\b", self.spoken)
        self.assertGreaterEqual(len(words), 240)
        self.assertLessEqual(len(words), 340)

    def test_primary_beats_are_headings_in_order(self):
        desk = self.lower.split("## three-minute desk round", 1)[1].split(
            "## five-minute finalist extension", 1
        )[0]
        positions = []
        for beat in BEATS:
            heading = f"### {beat}"
            self.assertIn(heading, desk)
            positions.append(desk.index(heading))
        self.assertEqual(positions, sorted(positions))

    def test_results_remain_placeholders(self):
        self.assertNotRegex(self.spoken, r"\d")
        self.assertGreaterEqual(self.spoken.count("__"), 6)
        for label in (
            "zone accuracy __",
            "presence accuracy __",
            "decision latency __",
            "images stored __",
            "bytes sent outside our local network __",
        ):
            self.assertIn(label, self.spoken_lower)

    def test_compute_and_screen_roles_are_clear(self):
        self.assertIn("the laptop shows the local interface", self.spoken_lower)
        self.assertIn(
            "the raspberry pi supplies network and radio, but it runs no model",
            self.spoken_lower,
        )
        self.assertIn("dragonwing cpu", self.spoken_lower)

    def test_unshipped_beats_have_an_explicit_gate(self):
        gates = self.lower.split("## feature gates", 1)[1]
        self.assertIn("does not yet contain", gates)
        self.assertIn("armed phone-alert", gates)
        self.assertIn("room-question", gates)
        self.assertIn("never stage a fake alert or answer", gates)

    def test_finalist_features_follow_the_primary_story(self):
        finalist = self.lower.split("## five-minute finalist extension", 1)[1]
        for phrase in (
            "whole-hall view",
            "no-movement alert",
            "tray",
            "router advice",
            "end-of-demo recap",
            "crowd game",
        ):
            self.assertIn(phrase, finalist)


if __name__ == "__main__":
    unittest.main()
