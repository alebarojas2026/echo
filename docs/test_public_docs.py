import re
import unittest
from pathlib import Path


DOCS = Path(__file__).parent

PROHIBITED_PATTERNS = (
    re.compile(r"fall detection", re.I),
    re.compile(r"sees through walls", re.I),
    re.compile(r"security system", re.I),
    re.compile(r"\bNPU\b"),
)


class PublicDocsTest(unittest.TestCase):
    def test_video_shots_cover_one_continuous_minute(self):
        text = (DOCS / "video-shots.md").read_text(encoding="utf-8")
        spans = re.findall(
            r"^## (\d+):(\d{2})[–-](\d+):(\d{2}) — ", text, re.MULTILINE
        )

        self.assertGreater(len(spans), 0)
        cursor = 0
        for start_m, start_s, end_m, end_s in spans:
            start = int(start_m) * 60 + int(start_s)
            end = int(end_m) * 60 + int(end_s)
            self.assertEqual(start, cursor, "shot list has a gap or overlap")
            self.assertGreater(end, start, "every shot needs positive duration")
            cursor = end

        self.assertEqual(cursor, 60)

    def test_video_proof_card_uses_placeholders(self):
        text = (DOCS / "video-shots.md").read_text(encoding="utf-8")
        for label in (
            "Dead-zone improvement",
            "Presence accuracy",
            "End-to-end update latency",
        ):
            self.assertRegex(text, rf"`{re.escape(label)}: __`")

    def test_devpost_measured_results_use_placeholders(self):
        text = (DOCS / "devpost-draft.md").read_text(encoding="utf-8")
        claims = re.findall(r"(?:Our|The) measured[^.]*\.", text)
        self.assertGreater(len(claims), 0)
        for claim in claims:
            self.assertIn("__", claim)

    def test_research_credit_is_present(self):
        text = (DOCS / "credits.md").read_text(encoding="utf-8")
        for phrase in (
            "Joey Wilson",
            "Neal Patwari",
            "Radio Tomographic Imaging with Wireless Networks",
            "2010",
        ):
            self.assertIn(phrase, text)

    def test_public_markdown_avoids_prohibited_claims(self):
        public_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in DOCS.glob("*.md")
        )
        for pattern in PROHIBITED_PATTERNS:
            self.assertIsNone(pattern.search(public_text))


if __name__ == "__main__":
    unittest.main()
