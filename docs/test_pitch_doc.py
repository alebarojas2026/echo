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
        cls.lower = cls.spoken.lower()

    def test_spoken_length_fits_ninety_seconds(self):
        words = re.findall(r"\b[\w'-]+\b", self.spoken)
        self.assertGreaterEqual(len(words), 180)
        self.assertLessEqual(len(words), 230)

    def test_required_demo_beats_are_spoken(self):
        for phrase in (
            "judge walks in",
            "radio x-ray",
            "this wave creates a check-in",
            "metal tray",
            "advisor recommends",
            "before the move",
            "after the move",
            "camera is now unplugged",
            "proof strip",
        ):
            self.assertIn(phrase, self.lower)

    def test_spoken_demo_beats_are_in_run_order(self):
        beats = (
            "judge walks in",
            "this wave creates a check-in",
            "metal tray",
            "before the move",
            "after the move",
            "camera is now unplugged",
            "proof strip",
        )
        positions = [self.lower.index(beat) for beat in beats]
        self.assertEqual(positions, sorted(positions))

    def test_results_remain_placeholders(self):
        self.assertNotRegex(self.spoken, r"\d")
        self.assertGreaterEqual(self.spoken.count("__"), 8)
        self.assertIn("__ dBm", self.spoken)

    def test_compute_and_screen_roles_are_clear(self):
        self.assertIn("this laptop shows the local interface", self.lower)
        self.assertIn("the pi supplies network and radio but runs no model", self.lower)
        self.assertNotIn("pi provides the sensing network and screen", self.lower)


if __name__ == "__main__":
    unittest.main()
