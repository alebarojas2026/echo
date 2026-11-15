import re
import unittest
from pathlib import Path


DRAFT = Path(__file__).with_name("devpost-draft.md")
PROOF = DRAFT.parents[1] / "PROOF.md"
PITCH = DRAFT.with_name("pitch.md")
RUNBOOK = DRAFT.with_name("demo-runbook.md")
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

    def test_building_safety_story_leads(self):
        self.assertTrue(
            self.text.startswith(
                "# Radio Sight: Safety and After-Hours Security with Wi-Fi"
            )
        )
        first_sentence = self.text.split("## Inspiration", 1)[1].strip().split("\n\n", 1)[0]
        self.assertIn("using the Wi-Fi already there", first_sentence)
        self.assertIn("no permanent camera", first_sentence)
        for audience in (
            "patient rooms",
            "bathrooms",
            "study rooms",
            "offices after hours",
        ):
            self.assertIn(audience, self.lower)

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

    def test_verified_product_comparisons_are_narrow(self):
        difference = self.lower.split("### how it is different", 1)[1].split(
            "## how we built it", 1
        )[0]
        for phrase in (
            "commercial wi-fi products make different architecture choices",
            "aerial.ai/motion-intelligence",
            "originwirelessai.com/trupresence-2",
            "documentation.meraki.com",
            "detecting wi-fi and bluetooth client devices",
            "does not need to carry the device being located",
        ):
            self.assertIn(phrase, difference)
        self.assertNotIn("all existing", difference)
        self.assertNotIn("all commercial", difference)

    def test_hardware_is_a_building_infrastructure_stand_in(self):
        built = self.lower.split("## how we built it", 1)[1].split(
            "## challenges", 1
        )[0]
        self.assertIn("stand in for access points and radios", built)
        self.assertIn("already distributed through a building", built)
        self.assertIn("a laptop browser shows the local interface", built)
        self.assertIn("routes it to the uno q over direct ethernet", built)
        self.assertIn("the pi supplies the private hotspot", self.lower)
        self.assertIn("runs no model", self.lower)

    def test_unfinished_integrations_are_not_claimed_live(self):
        self.assertIn("one honest line about what does not work yet", self.lower)
        self.assertIn("still being integrated into `main`", self.lower)
        self.assertIn("no unfinished beat will be staged as live", self.lower)

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

    def test_story_beats_match_pitch_and_runbook(self):
        pitch = PITCH.read_text(encoding="utf-8").lower()
        runbook = RUNBOOK.read_text(encoding="utf-8").lower()
        primary_sections = (
            (
                self.lower.split("the primary story uses", 1)[1].split(
                    "the measured zone accuracy", 1
                )[0],
                "- **{}:**",
            ),
            (
                pitch.split("## three-minute desk round", 1)[1].split(
                    "## five-minute finalist extension", 1
                )[0],
                "### {}",
            ),
            (
                runbook.split("## three-minute desk round", 1)[1].split(
                    "## camera-unplug proof", 1
                )[0],
                "**{}:**",
            ),
        )
        for text, marker in primary_sections:
            for beat in BEATS:
                self.assertIn(marker.format(beat), text)
            positions = [text.index(marker.format(beat)) for beat in BEATS]
            self.assertEqual(positions, sorted(positions))


if __name__ == "__main__":
    unittest.main()
