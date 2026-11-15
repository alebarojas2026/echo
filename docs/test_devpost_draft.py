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

    def test_building_story_and_audiences_lead(self):
        for phrase in (
            "safety and after-hours security",
            "using the wi-fi already there",
            "patient rooms",
            "bathrooms",
            "study rooms",
            "offices after hours",
        ):
            self.assertIn(phrase, self.lower)

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
        self.assertGreaterEqual(self.text.count("__"), 8)
        self.assertIn("../PROOF.md", self.text)

    def test_product_comparisons_are_verified_and_narrow(self):
        for phrase in (
            "products make different architecture choices",
            "aerial.ai/motion-intelligence",
            "originwirelessai.com/trupresence-2",
            "documentation.meraki.com",
        ):
            self.assertIn(phrase, self.lower)
        self.assertNotIn("all existing", self.lower)

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

    def test_unfinished_features_and_hardware_are_accurate(self):
        self.assertIn("still being integrated into `main`", self.lower)
        self.assertIn("no unfinished beat will be staged as live", self.lower)
        self.assertIn("stand in for access points and radios", self.lower)

    def test_screen_path_matches_the_live_demo(self):
        self.assertIn("a laptop browser shows the local interface", self.lower)
        self.assertIn("routes it to the uno q over direct ethernet", self.lower)
        self.assertNotIn("drives the screen", self.lower)

    def test_story_beats_match_pitch_and_runbook(self):
        pitch = PITCH.read_text(encoding="utf-8").lower()
        runbook = RUNBOOK.read_text(encoding="utf-8").lower()
        for beat in (
            "found you",
            "teach the room",
            "camera unplug",
            "still follows",
            "arm the space",
            "intrusion alert",
            "ask the room",
            "proof",
        ):
            self.assertIn(beat, self.lower)
            self.assertIn(beat, pitch)
            self.assertIn(beat, runbook)


if __name__ == "__main__":
    unittest.main()
