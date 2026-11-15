import re
import unittest
from pathlib import Path

from beats import BEATS, CORE


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
        for phrase in BEATS:
            self.assertIn(f"### {phrase.lower()}", self.lower)
        self.assertEqual(len(re.findall(r"^### ", self.text, re.M)), len(BEATS))

    def test_demo_beats_are_in_run_order(self):
        beats = [f"### {beat.lower()}\n" for beat in BEATS]
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

    def test_feature_status_is_current(self):
        self.assertIn("a beat is said only when it passed preflight on the day", self.lower)
        self.assertIn("never stage a fake alert, answer, replay or report", self.lower)

    def test_live_trace_ask_and_intrusion_words_match_the_product(self):
        for phrase in (
            "radio links on each side",
            "each shows that side's deepest drop",
            "works out which records the question is about",
            "a passer-by gets no alert",
            "person who remains raises one intrusion alert",
        ):
            self.assertIn(phrase, self.spoken.lower())

    def test_the_short_visit_names_what_to_drop_and_what_never_to_drop(self):
        short = self.text.split("## When the judge is short on time", 1)[1].split("## ", 1)[0]
        dropped = re.findall(r"^\d+\. \*\*(.+?)\*\*", short, re.M)
        self.assertEqual(dropped[:5], ["Replay", "Incident report", "Tamper alert", "Live signal", "Ask the room"])
        for beat in CORE:
            self.assertIn(f"**{beat}**", short.split("\n\n")[1])
            self.assertNotIn(beat, dropped)


if __name__ == "__main__":
    unittest.main()
