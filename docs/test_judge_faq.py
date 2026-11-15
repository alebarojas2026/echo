import re
import unittest
from pathlib import Path


class JudgeFaqTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = Path(__file__).with_name("judge-faq.md").read_text()
        cls.lower = cls.text.lower()
        cls.questions = re.findall(
            r"^## ([^\n]+\?)\n\n(.*?)(?=\n\n## |\Z)",
            cls.text, re.MULTILINE | re.DOTALL,
        )

    def test_exactly_twenty_answers_each_two_sentences_under_forty_words(self):
        self.assertEqual(len(self.questions), 20)
        for question, answer in self.questions:
            with self.subTest(question=question):
                self.assertLessEqual(len(answer.split()), 40)
                self.assertEqual(len(re.findall(r"[.!?](?:\s|$)", answer)), 2)
                self.assertNotIn("__", answer)

    def test_tripwire_distinction_keeps_hidden_placement_unmeasured(self):
        answer = self.questions[0][1].lower()
        for phrase in ("bag", "panel", "needs testing", "one strand",
                       "person versus thing", "still versus moving", "building wi-fi"):
            self.assertIn(phrase, answer)

    def test_hard_questions_and_current_boundaries(self):
        for phrase in ("threshold", "csi", "two people", "recording me", "cloud",
                       "dead zone", "pi a stays beside the cabled hub",
                       "clearing the object or moving pi b", "spoof", "jamming",
                       "single point of failure", "held-out accuracy", "language model",
                       "lean aside", "cost", "libraries", "let's dig in"):
            self.assertIn(phrase, self.lower)
        self.assertNotIn("__", self.text)
        for stale in ("wave", "east/west", "five boards", "esp32"):
            self.assertNotIn(stale, self.lower)


if __name__ == "__main__":
    unittest.main()
