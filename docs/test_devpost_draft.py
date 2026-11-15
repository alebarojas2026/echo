import re
import unittest
from pathlib import Path

from beats import BEATS

DRAFT = Path(__file__).with_name("devpost-draft.md")


class DevpostDraftTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = DRAFT.read_text()
        cls.lower = cls.text.lower()

    def test_paste_ready_sections_and_credits(self):
        for heading in ("Inspiration", "What it does", "How we built it", "Challenges",
                        "Accomplishments", "What we learned", "What's next",
                        "Built with", "Team", "Images"):
            self.assertIn(f"## {heading}", self.text)
        for phrase in ("MadHacks 2026", "Qualcomm / N+1", "Let's Dig In",
                       "Alexander", "Izet", "Ivan", "Alejandro"):
            self.assertIn(phrase, self.text)

    def test_images_have_live_rules_and_board_captions(self):
        images = self.text.split("## Images", 1)[1].split("## Built with", 1)[0]
        rows = [line for line in images.splitlines() if re.match(r"\| \d+\.", line)]
        self.assertEqual(len(rows), 8)
        for row in rows:
            self.assertIn("Arduino UNO Q", row.split("|")[-2])
        for phrase in ("live desk", "no recognisable face", "no camera frame",
                       "outside the repository", "one spot and three devices"):
            self.assertIn(phrase, images)

    def test_proof_blanks_stay_in_proof_section(self):
        proof = self.text.split("### Proof", 1)[1].split("### ", 1)[0]
        self.assertEqual(self.text.count("__"), proof.count("__"))
        self.assertIn("| Presence accuracy | __ |", proof)
        self.assertIn("held-out validation", proof)

    def test_devpost_links_are_absolute(self):
        links = re.findall(r"\[[^]]+\]\(([^)]+)\)", self.text)
        self.assertGreaterEqual(len(links), 3)
        for link in links:
            self.assertTrue(link.startswith("https://"), link)

    def test_six_story_beats_match_pitch_and_runbook(self):
        positions = [self.text.index(f"- **{beat}:**") for beat in BEATS]
        self.assertEqual(positions, sorted(positions))
        for filename in ("pitch.md", "demo-runbook.md"):
            other = DRAFT.with_name(filename).read_text()
            for beat in BEATS:
                self.assertIn(beat, other)

    def test_current_kit_privacy_and_honest_limits(self):
        for phrase in ("Walk between two devices and the Wi-Fi signal gives you away.",
                       "Bluetooth", "second opinion", "Pi A stays beside the cabled hub",
                       "clearing the object or moving Pi B", "with nobody there",
                       "no unfinished beat will be staged as live", "radios hidden in bags or panels",
                       "no camera image is saved", "neither pi runs a model",
                       "missing history remains unknown", "no cloud service"):
            self.assertIn(phrase.lower(), self.lower)
        for stale in ("which side", "wave", "each side", "moving the router"):
            self.assertNotIn(stale, self.lower)


if __name__ == "__main__":
    unittest.main()
