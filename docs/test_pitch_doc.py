import re
import unittest
from pathlib import Path

from beats import BEATS, CORE


PITCH = Path(__file__).with_name("pitch.md")
PROOF = PITCH.parents[1] / "PROOF.md"


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
        self.assertLessEqual(len(words), 340)

    def test_first_four_beats_leave_time_for_questions(self):
        desk_round = self.text.split("## Three-minute desk round", 1)[1].split(
            "## Five-minute finalist extension", 1
        )[0]
        sections = re.findall(
            r"^### [^\n]+\n(.*?)(?=^### |\Z)", desk_round, re.M | re.S
        )
        spoken = " ".join(
            line.removeprefix("> ")
            for section in sections[:4]
            for line in section.splitlines()
            if line.startswith("> ")
        )
        self.assertLessEqual(len(re.findall(r"\b[\w'-]+\b", spoken)), 170)

    def test_required_demo_beats_are_present(self):
        for phrase in BEATS:
            self.assertIn(f"### {phrase.lower()}", self.lower)
        self.assertEqual(len(re.findall(r"^### ", self.text, re.M)), len(BEATS))

    def test_demo_beats_are_in_run_order(self):
        beats = [f"### {beat.lower()}\n" for beat in BEATS]
        positions = [self.lower.index(beat) for beat in beats]
        self.assertEqual(positions, sorted(positions))

    def test_spoken_lines_do_not_read_blanks_or_unproved_numbers(self):
        self.assertNotIn("__", self.spoken)
        proof = PROOF.read_text(encoding="utf-8")
        for token in re.findall(r"\b\d+(?:\.\d+)?\b", self.spoken):
            self.assertIn(token, proof)

    def test_compute_and_screen_roles_are_clear(self):
        self.assertIn("qualcomm", self.spoken.lower())
        self.assertIn("dragonwing cpu", self.spoken.lower())

    def test_qualcomm_and_on_device_land_immediately_after_found_you(self):
        after_found = self.spoken.lower().split("found you", 1)[1]
        first_sixty = " ".join(re.findall(r"\b[\w'-]+\b", after_found)[:60])
        self.assertIn("qualcomm", first_sixty)
        self.assertIn("on device", first_sixty)

    def test_theme_and_ask_close_the_pitch(self):
        for phrase in (
            "we dug into a signal every building already has",
            "it can't see you, it can't be edited, and it still tells you exactly what happened",
            "we would like to keep building it",
        ):
            self.assertIn(phrase, self.spoken.lower())

    def test_spoken_numbers_are_sentences_we_may_say(self):
        allowed = PITCH.with_name("numbers-to-say.md").read_text(encoding="utf-8")
        for sentence in re.split(r"(?<=[.!?]) ", self.spoken):
            if re.search(r"\d", sentence):
                self.assertIn(sentence, allowed)

    def test_nothing_cut_from_the_product_is_spoken_or_planned(self):
        for cut in ("taught by", "camera unplug", "lesson", "dead zone", "beacon", "bluetooth",
                    "move the router", "lean aside", "passed by", "walk-through", "walked through"):
            self.assertNotIn(cut, self.lower)

    def test_feature_status_is_current(self):
        self.assertIn("a beat is shown only after it passes preflight", self.lower)
        self.assertNotIn("not complete", self.lower)
        self.assertNotIn("not ready", self.lower)


if __name__ == "__main__":
    unittest.main()
