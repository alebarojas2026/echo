import unittest
from pathlib import Path


CREDITS = Path(__file__).with_name("credits.md")


class CreditsDocTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = CREDITS.read_text(encoding="utf-8")
        cls.lower = cls.text.lower()

    def test_committed_test_dependency_is_credited(self):
        for phrase in (
            "pytest",
            "Unpinned",
            "MIT",
            "`bus/`",
            "`sim/`",
            "development and test tooling",
        ):
            self.assertIn(phrase, self.text)

    def test_stale_manifest_placeholder_is_gone(self):
        self.assertNotIn(
            "does not yet contain third-party dependency manifests", self.lower
        )

    def test_research_credit_remains_complete(self):
        for phrase in (
            "Joey Wilson",
            "Neal Patwari",
            "Radio Tomographic Imaging with Wireless Networks",
            "2010",
        ):
            self.assertIn(phrase, self.text)


if __name__ == "__main__":
    unittest.main()
