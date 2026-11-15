import re
import unittest
from pathlib import Path


class JudgeFaqTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = Path(__file__).with_name("judge-faq.md").read_text(encoding="utf-8")
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

    def test_hard_questions_and_honest_limits(self):
        for phrase in ("tripwire", "threshold", "csi", "two people", "recording me", "cloud",
                       "not edited", "forging both signatures", "spoof", "jamming",
                       "single point of failure", "language model", "step aside and back",
                       "cost", "let's dig in", "senses one spot", "does not count people",
                       "a few seconds on the line", "desk height", "no camera and no microphone"):
            self.assertIn(phrase, self.lower)
        self.assertNotIn("__", self.text)

    def test_numbers_are_sentences_we_may_say(self):
        allowed = Path(__file__).with_name("numbers-to-say.md").read_text(encoding="utf-8")
        for _, answer in self.questions:
            for sentence in re.split(r"(?<=[.!?]) ", answer):
                if re.search(r"\d", sentence):
                    self.assertIn(sentence, allowed)

    def test_nothing_cut_from_the_product_is_claimed(self):
        for cut in ("taught by", "lesson", "dead zone", "beacon", "bluetooth", "move the router",
                    "lean aside", "wave", "esp32", "passed by", "walked through", "second opinion"):
            self.assertNotIn(cut, self.lower)


if __name__ == "__main__":
    unittest.main()
