import re
import unittest
from pathlib import Path


PITCH = Path(__file__).with_name("pitch.md")


class PitchDocTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = PITCH.read_text(encoding="utf-8")
        cls.spoken = " ".join(
            line.removeprefix("> ")
            for line in cls.text.splitlines()
            if line.startswith("> ")
        )
        cls.lower = cls.text.lower()

    def test_spoken_length_fits_three_minute_demo(self):
        words = re.findall(r"\b[\w'-]+\b", self.spoken)
        self.assertGreaterEqual(len(words), 240)
        self.assertLessEqual(len(words), 340)

    def test_required_demo_beats_are_present(self):
        for phrase in (
            "found you",
            "teach the room",
            "camera unplug",
            "still follows",
            "arm the space",
            "intrusion alert",
            "ask the room",
            "proof",
        ):
            self.assertIn(f"### {phrase}", self.lower)

    def test_demo_beats_are_in_run_order(self):
        beats = (
            "### found you",
            "### teach the room",
            "### camera unplug",
            "### still follows",
            "### arm the space",
            "### intrusion alert",
            "### ask the room",
            "### proof",
        )
        positions = [self.lower.index(beat) for beat in beats]
        self.assertEqual(positions, sorted(positions))

    def test_results_remain_placeholders(self):
        self.assertNotRegex(self.spoken, r"\d")
        self.assertGreaterEqual(self.spoken.count("__"), 6)
        self.assertIn("images stored __", self.spoken.lower())

    def test_compute_and_screen_roles_are_clear(self):
        self.assertIn("the laptop shows the local interface", self.spoken.lower())
        self.assertIn("raspberry pi supplies network and radio", self.spoken.lower())
        self.assertIn("it runs no model", self.spoken.lower())
        self.assertIn("dragonwing cpu", self.spoken.lower())


if __name__ == "__main__":
    unittest.main()
