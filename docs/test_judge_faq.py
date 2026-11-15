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

    def test_every_spoken_answer_is_short_and_complete(self):
        self.assertGreaterEqual(len(self.questions), 25)
        for question, answer in self.questions:
            with self.subTest(question=question):
                self.assertLessEqual(len(answer.split()), 40)
                self.assertNotIn("__", answer)

    def test_technical_judge_questions_are_covered(self):
        for phrase in (
            "threshold", "so few links", "work on me", "two people",
            "misuse", "spoofing or jamming", "csi or radar", "breaks first",
            "board dies", "scale", "cost", "what is a library",
            "let's dig in", "keep building", "how accurate", "dead spot",
            "on-device", "recording me", "radio x-ray",
        ):
            self.assertIn(phrase, self.lower)

    def test_current_kit_and_honest_limits(self):
        for phrase in (
            "wi-fi between the pis is the main sensor", "second opinion",
            "one spot", "three devices", "two raspberry pis", "lean aside",
            "neither raspberry pi runs a model", "dragonwing cpu",
            "stores no camera images", "blind required link pauses the timer",
            "single point of failure", "held-out accuracy", "not a building",
        ):
            self.assertIn(phrase, self.lower)
        self.assertNotIn("__", self.text)
        for stale in ("wave", "east/west", "five boards", "esp32"):
            self.assertNotIn(stale, self.lower)


if __name__ == "__main__":
    unittest.main()
