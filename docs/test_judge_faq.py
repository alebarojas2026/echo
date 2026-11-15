import re
import unittest
from pathlib import Path


FAQ = Path(__file__).with_name("judge-faq.md")


class JudgeFaqTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = FAQ.read_text(encoding="utf-8")
        cls.lower = cls.text.lower()
        question_pattern = re.compile(
            r"^## ([^\n]+\?)\n\n(.*?)(?=\n\n## |\Z)", re.MULTILINE | re.DOTALL
        )
        cls.questions = question_pattern.findall(cls.text)

    def test_has_fourteen_questions_with_short_answers(self):
        self.assertEqual(len(self.questions), 14)
        for question, answer in self.questions:
            with self.subTest(question=question):
                sentences = re.findall(r"[^.!?]+[.!?]", answer)
                self.assertGreaterEqual(len(sentences), 2)
                self.assertLessEqual(len(sentences), 3)

    def test_required_hard_questions_and_honest_limits_are_present(self):
        for phrase in (
            "why are there so many boards",
            "why not just use a camera",
            "why not use a motion sensor or radar",
            "can it identify people or count a crowd",
            "does it work in any building",
            "what happens in a wi-fi dead spot",
            "why run it on-device",
            "what runs on the arduino uno q",
            "why is there a raspberry pi too",
            "how do you protect privacy",
            "how accurate is it",
            "what can radio sight not do yet",
            "## honest limits",
        ):
            self.assertIn(phrase, self.lower)

    def test_contract_and_hardware_boundaries_are_clear(self):
        for phrase in (
            "dragonwing cpu",
            "pi provides the private sensing hotspot",
            "routes the laptop browser to the board",
            "raspberry pi runs no model",
            "stores no camera images",
            "no-movement alert",
            "blind required link pauses the timer",
            "one intrusion event",
        ):
            self.assertIn(phrase, self.lower)

    def test_identity_crowd_and_building_limits_are_explicit(self):
        identity = self.lower.split(
            "## can it identify people or count a crowd?", 1
        )[1].split("## does it work in any building?", 1)[0]
        self.assertIn("no:", identity)
        self.assertIn("not identity", identity)
        self.assertIn("does not claim crowd counting", identity)

        building = self.lower.split("## does it work in any building?", 1)[1].split(
            "## what happens in a wi-fi dead spot?", 1
        )[0]
        self.assertIn("compatible radios", building)
        self.assertIn("measured only in its current setup", building)
        self.assertIn("__` seconds", building)

    def test_unmeasured_results_are_placeholders(self):
        self.assertGreaterEqual(self.text.count("__"), 5)
        self.assertNotRegex(
            self.text, r"\b\d+(?:\.\d+)?\s*(?:%|ms|s|w|dbm|db|bytes?)\b"
        )

    def test_unfinished_features_are_named(self):
        limits = self.lower.split("## what can radio sight not do yet?", 1)[1]
        self.assertIn("armed phone-alert", limits)
        self.assertIn("room-question integrations are not yet in `main`", limits)
        self.assertIn("full coverage mapping still need measured tests", limits)


if __name__ == "__main__":
    unittest.main()
