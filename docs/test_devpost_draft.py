import re
import unittest
from pathlib import Path

from beats import BEATS

DRAFT = Path(__file__).with_name("devpost-draft.md")
NUMBERS = DRAFT.with_name("numbers-to-say.md")


class DevpostDraftTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = DRAFT.read_text(encoding="utf-8")
        cls.lower = cls.text.lower()

    def test_paste_ready_sections_and_credits(self):
        for heading in ("Inspiration", "What it does", "How we built it", "Challenges",
                        "Accomplishments", "What we learned", "What's next",
                        "Built with", "Team", "Images"):
            self.assertIn(f"## {heading}", self.text)
        for phrase in ("MadHacks 2026", "Qualcomm / N+1", "Let's Dig In",
                       "Alexander", "Izet", "Ivan", "Alejandro"):
            self.assertIn(phrase, self.text)
        self.assertTrue(self.text.startswith("# Echo\n"))

    def test_images_have_live_rules_and_board_captions(self):
        images = self.text.split("## Images", 1)[1].split("## Built with", 1)[0]
        rows = [line for line in images.splitlines() if re.match(r"\| \d+\.", line)]
        self.assertEqual(len(rows), 8)
        for row in rows:
            self.assertIn("Arduino UNO Q", row.split("|")[-2])
        for phrase in ("live desk", "no recognisable face", "outside the repository",
                       "one spot and three devices"):
            self.assertIn(phrase, images)

    def test_every_number_in_the_proof_section_is_a_sentence_we_may_say(self):
        proof = self.text.split("### Proof", 1)[1].split("## ", 1)[0]
        allowed = NUMBERS.read_text(encoding="utf-8")
        bullets = [line[2:] for line in proof.splitlines() if line.startswith("- ")]
        self.assertEqual(len(bullets), 8)
        for bullet in bullets:
            self.assertIn(f'"{bullet}"', allowed)
        self.assertNotIn("__", self.text)
        self.assertIn("held-out set only", proof)

    def test_the_text_carries_no_links_while_the_repository_is_private(self):
        self.assertEqual(re.findall(r"\]\(([^)]+)\)", self.text), [])

    def test_six_story_beats_match_pitch_and_runbook(self):
        positions = [self.text.index(f"- **{beat}:**") for beat in BEATS]
        self.assertEqual(positions, sorted(positions))
        for filename in ("pitch.md", "demo-runbook.md"):
            other = DRAFT.with_name(filename).read_text(encoding="utf-8")
            for beat in BEATS:
                self.assertIn(beat, other)

    def test_the_witness_and_its_honest_limits(self):
        for phrase in ("a witness that never watches", "can't see you, can't be edited",
                       "sha-256 hash of the one before it", "ed25519", "from the sealed record only",
                       "the real record is never touched", "it senses one spot",
                       "does not know who a person is", "a few seconds on the line",
                       "neither pi runs a model", "calls no cloud service", "no trained model",
                       "### what runs on the uno q", "four cortex-a53 cores", "step aside and back",
                       "\"architecture\" and \"data path\""):
            self.assertIn(phrase, self.lower)

    def test_nothing_cut_from_the_product_is_claimed(self):
        for cut in ("taught by", "camera unplug", "lesson", "dead zone", "dead-zone", "beacon",
                    "second opinion", "moving the router", "which side", "wave", "passed by",
                    "walk-through", "walked through", "nothing is sent to the internet", "0 bytes",
                    "the others carry on", "blockchain", "unhackable", "tamper-proof"):
            self.assertNotIn(cut, self.lower)


if __name__ == "__main__":
    unittest.main()
