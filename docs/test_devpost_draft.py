import re
import unittest
from pathlib import Path


DRAFT = Path(__file__).with_name("devpost-draft.md")
PROOF = DRAFT.parents[1] / "PROOF.md"
PITCH = DRAFT.with_name("pitch.md")
RUNBOOK = DRAFT.with_name("demo-runbook.md")


class DevpostDraftTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = DRAFT.read_text(encoding="utf-8")
        cls.lower = cls.text.lower()

    def test_required_sections_are_present(self):
        for heading in (
            "Inspiration",
            "What it does",
            "How we built it",
            "Challenges",
            "Accomplishments",
            "What we learned",
            "What's next",
        ):
            self.assertIn(f"## {heading}", self.text)

    def test_contract_v2_demo_features_are_named(self):
        for phrase in (
            "radio x-ray",
            "person-vs-object",
            "check-in",
            "on-board narrator",
            "dead-zone advisor",
            "camera is then unplugged",
            "no-movement alert",
        ):
            self.assertIn(phrase, self.lower)

    def test_measured_claims_remain_placeholders(self):
        measured_sentences = re.findall(
            r"[^.]*\bmeasured\b[^.]*\bis\b[^.]*\.", self.text, re.I
        )
        self.assertGreater(len(measured_sentences), 0)
        for sentence in measured_sentences:
            self.assertIn("__", sentence)

    def test_every_numeric_token_is_backed_by_proof(self):
        proof = PROOF.read_text(encoding="utf-8")
        for token in re.findall(r"\b\d+(?:\.\d+)?\b", self.text):
            self.assertIn(token, proof)
        self.assertGreaterEqual(self.text.count("__"), 6)
        self.assertIn("../PROOF.md", self.text)

    def test_built_with_and_team_roles_are_complete(self):
        for phrase in (
            "## Built with",
            "Arduino UNO Q",
            "Qualcomm Dragonwing",
            "scikit-learn",
            "OpenCV",
            "Three.js",
            "WebSockets",
            "## Team",
            "Alexander",
            "Izet",
            "Ivan",
            "Alejandro",
        ):
            self.assertIn(phrase, self.text)

    def test_unmerged_extras_are_described_as_next_steps(self):
        whats_next = self.text.split("## What's next", 1)[1]
        self.assertIn("end-of-demo recap", whats_next.lower())
        self.assertIn("caregiver phone page", whats_next.lower())

    def test_story_beats_match_pitch_and_runbook(self):
        pitch = PITCH.read_text(encoding="utf-8").lower()
        runbook = RUNBOOK.read_text(encoding="utf-8").lower()
        for beat in (
            "judge walks in",
            "radio x-ray",
            "wave check-in",
            "no-movement alert",
            "tray vs person",
            "router advice",
            "camera unplug",
            "proof",
        ):
            self.assertIn(beat, self.lower)
            self.assertIn(beat, pitch)
            self.assertIn(beat, runbook)

if __name__ == "__main__":
    unittest.main()
