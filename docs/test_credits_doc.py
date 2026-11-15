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
            "`brain/`",
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
            "scikit-learn",
            "OpenCV (`cv2`)",
            "Apache-2.0",
            "Not pinned in this repository",
            "`advisor/`",
            "`brain/`",
            "`narrator/`",
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
            "`@playwright/test`",
            "`1.60.0`",
            "`contracts/`",
            "`web/`",
            "`web/tests/`",
        ):
            self.assertIn(phrase, self.text)

    def test_current_brain_manifest_dependencies_are_credited(self):
        for phrase in (
            "NumPy",
            "scikit-learn",
            "websockets",
            "pytest",
            "unpinned in `brain/`",
        ):
            self.assertIn(phrase, self.text)

    def test_current_board_manifest_dependencies_are_credited(self):
        rows = {
            columns[0].strip(): columns
            for line in self.text.splitlines()
            if line.startswith("|")
            for columns in ([column.strip() for column in line.split("|")[1:-1]],)
            if columns
        }

        for library in ("NumPy", "scikit-learn"):
            row = rows[library]
            self.assertEqual(row[1], "Unpinned")
            self.assertIn("`board/`", row[4])

    def test_demo_check_websocket_dependency_is_credited(self):
        websocket_row = next(
            line for line in self.text.splitlines() if line.startswith("| websockets |")
        )
        for phrase in ("`==17.1` in `scripts/`", "BSD-3-Clause", "`scripts/`"):
            self.assertIn(phrase, websocket_row)

    def test_scan_preparation_dependencies_are_credited(self):
        rows = {
            columns[0].strip(): columns
            for line in self.text.splitlines()
            if line.startswith("|")
            for columns in ([column.strip() for column in line.split("|")[1:-1]],)
            if columns
        }

        for library in (
            "`@gltf-transform/core`",
            "`@gltf-transform/extensions`",
            "`@gltf-transform/functions`",
        ):
            row = rows[library]
            self.assertEqual(row[1], "`^4.5.1`")
            self.assertEqual(row[2], "MIT")
            self.assertEqual(row[3], "3D asset preparation")
            self.assertIn("`web/`", row[4])
            self.assertIn("https://gltf-transform.dev/", row[5])

        meshoptimizer = rows["meshoptimizer"]
        self.assertEqual(meshoptimizer[1], "`^1.3.0`")
        self.assertEqual(meshoptimizer[2], "MIT")
        self.assertEqual(meshoptimizer[3], "3D asset preparation")
        self.assertIn("`web/`", meshoptimizer[4])
        self.assertIn("https://github.com/zeux/meshoptimizer", meshoptimizer[5])

    def test_typefaces_are_credited_with_their_licence_and_files(self):
        rows = {
            columns[0].strip(): columns
            for line in self.text.splitlines()
            if line.startswith("|")
            for columns in ([column.strip() for column in line.split("|")[1:-1]],)
            if columns
        }
        fonts = CREDITS.parent.parent / "web" / "src" / "hud" / "fonts"

        for typeface, weights, role, files in (
            ("Poppins", "400, 500, 600", "All text", ("poppins-400", "poppins-500", "poppins-600")),
            ("Tenor Sans", "400", "Titles", ("tenor-sans-400",)),
        ):
            row = rows[typeface]
            self.assertEqual(row[1], weights)
            self.assertEqual(row[2], "SIL Open Font License 1.1")
            self.assertEqual(row[3], role)
            self.assertIn("`web/`", row[4])
            for name in files:
                self.assertEqual((fonts / f"{name}.woff2").read_bytes()[:4], b"wOF2")
            licence = fonts / f"{files[0].rsplit('-', 1)[0]}-OFL.txt"
            self.assertIn("SIL OPEN FONT LICENSE Version 1.1", licence.read_text(encoding="utf-8"))

        self.assertNotIn("Hanken", self.text)
        self.assertFalse((fonts / "hanken-grotesk.woff2").exists())

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
