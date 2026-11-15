import re
import unittest
from pathlib import Path


DOCS = Path(__file__).parent
ARCHITECTURE = DOCS / "architecture.md"
PICTURE = DOCS / "architecture.svg"

# Parts that were cut from the product: nothing a judge reads may bring them back.
CUT = ("camera teacher", "camera lesson", "dead-zone", "dead zone", "router advisor",
       "move the router", "beacon", "esp32", "bluetooth", "lean aside", "radio sight",
       "walked through", "passed by")
CLAIMS_IT_MUST_NOT_MAKE = ("tracks", "locates", "pinpoints", "which side", "surveillance")
COLOURS = {"#101216", "#14171C", "#171A20", "#1B1F26", "#3A404A", "#F2F4F6", "#A3ABB6",
           "#1FA5CF", "#E5484D"}


def mermaid_blocks(text):
    return re.findall(r"```mermaid\n(.*?)```", text, re.DOTALL)


class ArchitectureDocTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = ARCHITECTURE.read_text(encoding="utf-8")
        cls.lower = cls.text.lower()
        cls.diagrams = mermaid_blocks(cls.text)
        cls.picture = PICTURE.read_text(encoding="utf-8")

    def test_the_product_is_called_echo(self):
        self.assertTrue(self.text.startswith("# Echo"))
        self.assertIn("a witness that never watches", self.lower)

    def test_main_diagram_shows_three_devices_one_line_and_the_edge(self):
        main = self.diagrams[0]
        for phrase in ("Pi A", "Pi B", "The board", "Arduino UNO Q", "Qualcomm Dragonwing QRB2210",
                       "THE ONE SENSING LINE", "Seals every record", "signature every 5 s",
                       "Screens", "one Ethernet cable",
                       "NO INTERNET · NO CAMERA · NO MICROPHONE",
                       "What an attacker would have to break"):
            self.assertIn(phrase, main)
        self.assertEqual(main.count("signature every 5 s"), 2, "one signature from each Pi")
        boxes = re.findall(r"^\s+[A-Z]+\[\"<b>", main, re.M)
        self.assertLessEqual(len(boxes), 9, "a judge reads this in ten seconds")

    def test_data_path_is_six_steps_in_order(self):
        path = self.diagrams[1]
        steps = re.findall(r"<b>(\d) (\w+)</b>", path)
        self.assertEqual(steps, [("1", "Reading"), ("2", "Decision"), ("3", "Record"),
                                 ("4", "Seal"), ("5", "Signature"), ("6", "Answer")])
        self.assertIn("R --> D --> W --> S --> G --> A", path)
        for rate in ("25 a second", "1 a second", "SHA-256", "Ed25519", "every 5 s"):
            self.assertIn(rate, path)

    def test_one_accent_colour_and_one_red(self):
        for drawing in (*self.diagrams, self.picture):
            colours = {c.upper() for c in re.findall(r"#[0-9A-Fa-f]{6}\b", drawing)}
            self.assertIn("#1FA5CF", colours)
            self.assertLessEqual(colours, COLOURS)

    def test_every_part_is_explained_in_plain_words(self):
        section = self.text.split("## How each part works", 1)[1].split("\n## ", 1)[0]
        for part in ("Pi A", "Pi B", "The sensing line", "The board", "The decision", "The record",
                     "The seal", "The signatures", "The answer", "The small language model",
                     "The screens", "The one Ethernet cable"):
            self.assertRegex(section, rf"- \*\*{re.escape(part)}[ .]")
        for line in section.splitlines():
            if line.startswith("- "):
                self.assertLessEqual(len(line), 420, "short enough to read aloud: " + line[:40])

    def test_limits_are_said_plainly(self):
        box = self.text.split("## What it does not do", 1)[1].split("\n## ", 1)[0].lower()
        for phrase in ("does not know **who**", "does not know **where**", "one spot",
                       "does not count people", "no camera and no microphone",
                       "nothing to the internet", "not been tested through a wall",
                       "a few seconds on the line"):
            self.assertIn(phrase, box)

    def test_cut_parts_and_forbidden_claims_are_absent(self):
        for where in (self.lower, self.picture.lower()):
            for phrase in CUT + CLAIMS_IT_MUST_NOT_MAKE:
                self.assertNotIn(phrase, where)

    def test_the_model_is_never_the_source_of_a_fact(self):
        self.assertIn("every fact, time and number comes from a record", self.lower)
        self.assertIn("the pis run no model", self.lower)

    def test_picture_is_a_plain_hand_made_svg(self):
        self.assertIn("](architecture.svg)", self.text)
        self.assertIn('viewBox="0 0 1920 1080"', self.picture)
        self.assertIn('role="img"', self.picture)
        for phrase in ("The one sensing line",
                       "Seals every record", "What an attacker would have to break",
                       "Hanken Grotesk"):
            self.assertIn(phrase, self.picture)
        for banned in ("<image", "<script", "Gradient", "filter=", 'href="http'):
            self.assertNotIn(banned, self.picture)


if __name__ == "__main__":
    unittest.main()
