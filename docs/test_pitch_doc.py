import re
import unittest
from pathlib import Path


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

    def test_first_five_beats_leave_time_for_questions(self):
        desk_round = self.text.split("## Three-minute desk round", 1)[1].split(
            "## Five-minute finalist extension", 1
        )[0]
        sections = re.findall(
            r"^### [^\n]+\n(.*?)(?=^### |\Z)", desk_round, re.M | re.S
        )
        spoken = " ".join(
            line.removeprefix("> ")
            for section in sections[:5]
            for line in section.splitlines()
            if line.startswith("> ")
        )
        self.assertLessEqual(len(re.findall(r"\b[\w'-]+\b", spoken)), 170)

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
            "taught by a camera. runs without one",
            "we would like to keep building it",
        ):
            self.assertIn(phrase, self.spoken.lower())

    def test_feature_status_is_current(self):
        self.assertIn("a beat is shown only after it passes preflight", self.lower)
        self.assertNotIn("not complete", self.lower)
        self.assertNotIn("not ready", self.lower)


if __name__ == "__main__":
    unittest.main()
