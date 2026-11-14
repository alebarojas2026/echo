import re
import unittest
from pathlib import Path


DESK = Path(__file__).with_name("desk-demo.md")
ROW = re.compile(r"^\| (\d+):(\d{2})-(\d+):(\d{2}) \|(.*)\|$", re.MULTILINE)


def seconds(m, s):
    return int(m) * 60 + int(s)


def section(text, heading):
    part = text.split(f"## {heading}\n", 1)[1]
    return part.split("\n## ", 1)[0]


class DeskDemoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = DESK.read_text(encoding="utf-8")
        cls.script = [(seconds(a, b), seconds(c, d), cells.split(" | "))
                      for a, b, c, d, cells in ROW.findall(section(cls.text, "The 3 minutes"))]
        cls.reset = [(seconds(a, b), seconds(c, d))
                     for a, b, c, d, _ in ROW.findall(section(cls.text, "Reset between judges (about 20 seconds)"))]

    def assert_back_to_back(self, spans):
        cursor = 0
        for start, end in spans:
            self.assertEqual(start, cursor, "a gap or an overlap in the times")
            self.assertGreater(end, start)
            cursor = end
        return cursor

    def test_three_minute_script_adds_up_to_180_s_or_less(self):
        self.assertGreaterEqual(len(self.script), 6)
        self.assertLessEqual(self.assert_back_to_back([(a, b) for a, b, _ in self.script]), 180)

    def test_every_line_says_what_the_presenter_judge_and_screen_do(self):
        for start, _, cells in self.script:
            self.assertEqual(len(cells), 3, start)
            self.assertTrue(all(cell.strip() for cell in cells), start)

    def test_twenty_second_opening_and_fifteen_second_close_with_proof_blanks(self):
        (o_start, o_end, _), (c_start, c_end, close) = self.script[0], self.script[-1]
        self.assertEqual((o_start, o_end), (0, 20))
        self.assertEqual(c_end - c_start, 15)
        said = close[0]
        self.assertGreaterEqual(said.count("__"), 3)
        self.assertEqual(re.findall(r"\d", said), [], "a proof number in the close that isn't measured")

    def test_the_four_fast_moments_in_order(self):
        said = " ".join(" ".join(cells) for _, _, cells in self.script).lower()
        beats = ("step into the sensing area", "stand still", "no-movement alert", "give it a wave", "pull its cable", "walk out", "proof strip")
        positions = [said.index(beat) for beat in beats]
        self.assertEqual(positions, sorted(positions))

    def test_later_moments_are_named(self):
        later = section(self.text, "If the judge has time").lower()
        for moment in ("tray", "router advice", "recap", "game"):
            self.assertIn(moment, later)

    def test_reset_fits_in_about_20_seconds(self):
        self.assertGreaterEqual(len(self.reset), 3)
        self.assertLessEqual(self.assert_back_to_back(self.reset), 20)
        steps = section(self.text, "Reset between judges (about 20 seconds)")
        self.assertIn("Reset demo", steps)

    def test_no_layout_detail_and_the_right_words(self):
        lower = self.text.lower()
        for word in ("marker", "tape", "metre", " cm", "npu", "fall detection", "security system"):
            self.assertNotIn(word, lower)
        self.assertIn("no-movement alert", lower)
        self.assertIn("dragonwing cpu", lower)


if __name__ == "__main__":
    unittest.main()
