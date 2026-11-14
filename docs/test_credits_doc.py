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
            "`narrator/`",
            "development and test tooling",
        ):
            self.assertIn(phrase, self.text)

    def test_runtime_dependencies_are_credited_honestly(self):
        for phrase in (
            "websockets",
            "`>=12`",
            "BSD-3-Clause",
            "NumPy",
            "OpenCV (`cv2`)",
            "Apache-2.0",
            "Not yet in a manifest",
            "`advisor/`",
            "`teacher/`",
        ):
            self.assertIn(phrase, self.text)

    def test_stale_manifest_placeholder_is_gone(self):
        self.assertNotIn(
            "does not yet contain third-party dependency manifests", self.lower
        )
        self.assertNotIn("one third-party package", self.lower)
        self.assertNotIn(
            "no third-party runtime library is currently declared", self.lower
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
