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
            "| Test |",
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
            "Not pinned in this repository",
            "`advisor/`",
            "`brain/`",
            "`teacher/`",
        ):
            self.assertIn(phrase, self.text)

    def test_contract_and_web_dependencies_are_credited(self):
        for phrase in (
            "jsonschema",
            "`>=4.18`",
            "referencing",
            "three",
            "`^0.187.0`",
            "Vite",
            "`^8.3.8`",
            "Vitest",
            "`^5.1.0`",
            "TypeScript",
            "`^7.0.2`",
            "`@types/three`",
            "`contracts/`",
            "`web/`",
        ):
            self.assertIn(phrase, self.text)

    def test_app_lab_bricks_are_credited(self):
        for phrase in (
            "Arduino App Bricks",
            "MPL-2.0",
            "`teacher/applab/`",
            "https://github.com/arduino/app-bricks-py",
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
