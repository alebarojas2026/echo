import re
import unittest
from pathlib import Path


PLAN = Path(__file__).with_name("game-plan.md")
TEAM = {"Alejandro", "Alexander", "Ivan", "Izet"}
ALLOWED_IPS = {"192.168.77.1", "192.168.77.2"}


def section(text, heading, level=2):
    stop = "#" * level
    match = re.search(
        rf"^{stop} {re.escape(heading)}\n(.*?)(?=^#{{2,{level}}} |\Z)", text, re.M | re.S
    )
    if not match:
        raise AssertionError(f"missing section: {heading}")
    return match.group(1)


def table_rows(body):
    rows = [line for line in body.splitlines() if line.startswith("| ")]
    return [[cell.strip() for cell in row.strip("|").split("|")] for row in rows[1:]]


class GamePlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = PLAN.read_text(encoding="utf-8")

    def test_has_every_part_of_the_plan(self):
        for heading in (
            "What a judge must leave with",
            "Roles on the day",
            "Timeline",
            "Presentation-room setup",
            "Three lengths of pitch",
            "Demo choreography",
            "Fallback ladder",
            "Q&A",
            "Rehearsals",
            "Between judges",
            "Packing list (Alexander)",
        ):
            section(self.text, heading)

    def test_roles_and_answers_belong_to_the_team(self):
        roles = table_rows(section(self.text, "Roles on the day"))
        self.assertEqual({row[1] for row in roles}, TEAM)
        hardware = [row for row in roles if row[0] == "Hardware"]
        self.assertEqual(hardware[0][1], "Alexander")
        for row in table_rows(section(self.text, "Q&A")):
            self.assertIn(row[1], TEAM, row[0])

    def test_short_pitches_fit_their_time(self):
        body = section(self.text, "Three lengths of pitch")
        for heading, limit in (
            ("10 seconds (someone walking past)", 25),
            ("30 seconds (a judge stops at the table)", 80),
        ):
            part = section(body, heading, level=3)
            spoken = " ".join(l[2:] for l in part.splitlines() if l.startswith("> "))
            words = re.findall(r"\b[\w'-]+\b", spoken)
            self.assertTrue(words, heading)
            self.assertLessEqual(len(words), limit, heading)

    def test_choreography_follows_the_pitch_order(self):
        beats = [row[0] for row in table_rows(section(self.text, "Demo choreography"))]
        order = ["Walk in", "Radio X-ray", "No-movement alert", "Wave check-in",
                 "Tray vs person", "Router advice", "Move router", "Camera unplug", "Proof strip"]
        self.assertEqual([b for b in beats if b in order], order)

    def test_fallback_ladder_is_honest_and_ordered(self):
        body = section(self.text, "Fallback ladder")
        rungs = re.findall(r"^(\d+)\. \*\*(.+?)\*\*", body, re.M)
        self.assertEqual([int(n) for n, _ in rungs], list(range(1, len(rungs) + 1)))
        self.assertEqual(rungs[0][1], "Full live demo.")
        self.assertIn("never called live", body)
        self.assertIn("python -m sim.replay", body)

    def test_tape_only_in_the_presentation_room(self):
        body = section(self.text, "Presentation-room setup")
        self.assertIn("Tape goes down only here", body)
        self.assertIn("20 s baseline", body)
        self.assertIn("SENSOR BLIND", body)

    def test_no_invented_results_or_addresses(self):
        self.assertNotRegex(self.text, r"\d+(\.\d+)?\s*%")
        self.assertNotRegex(self.text, r"\d+\s*(ms|dBm|Mbps)\b")
        for ip in re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", self.text):
            self.assertIn(ip, ALLOWED_IPS)


if __name__ == "__main__":
    unittest.main()
