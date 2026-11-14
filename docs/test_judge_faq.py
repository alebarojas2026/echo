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

    def test_has_twelve_questions_with_short_answers(self):
        self.assertEqual(len(self.questions), 12)
        for question, answer in self.questions:
            with self.subTest(question=question):
                sentences = re.findall(r"[^.!?]+[.!?]", answer)
                self.assertGreaterEqual(len(sentences), 2)
                self.assertLessEqual(len(sentences), 3)

    def test_required_topics_and_honest_limits_are_present(self):
        for phrase in (
            "why not just use a camera",
            "what runs on the arduino uno q",
            "why is there a raspberry pi too",
            "how do you protect privacy",
            "what happens if furniture moves",
            "how accurate is it",
            "what can radio sight not do",
            "## honest limits",
        ):
            self.assertIn(phrase, self.lower)

    def test_contract_boundaries_are_clear(self):
        for phrase in (
            "dragonwing cpu",
            "pi provides the private sensing hotspot",
            "it runs no model",
            "stores no camera images",
            "no-movement alert",
            "blind classifier link produces no prediction",
        ):
            self.assertIn(phrase, self.lower)

    def test_unmeasured_results_are_placeholders(self):
        self.assertGreaterEqual(self.text.count("__"), 3)
        self.assertNotRegex(self.text, r"\b\d+(?:\.\d+)?\s*(?:%|ms|s|w|dbm|db|bytes?)\b")


if __name__ == "__main__":
    unittest.main()
