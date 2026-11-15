import re
import unittest
from pathlib import Path

DOCS = Path(__file__).parent


class NumbersToSayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (DOCS / "numbers-to-say.md").read_text(encoding="utf-8")
        cls.proof = (DOCS.parent / "PROOF.md").read_text(encoding="utf-8")
        cls.sentences = re.findall(r'^\d\. "(.+)"$', cls.text, re.MULTILINE)

    def test_five_to_eight_sentences(self):
        self.assertTrue(5 <= len(self.sentences) <= 8)

    def test_every_quoted_number_is_a_row_of_the_proof_record(self):
        for phrase in ("10 of 10", "between 69% and 100%", "5 of 5", "between 47% and 100%", "9.4 empty minutes",
                       "under 0.4 a minute", "0.50 to 0.58", "170 of 170", "164 of 170", "0 of 5",
                       "replayed through the brain from recordings taken on the kit"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)
                self.assertIn(phrase, self.proof)
        for value in ("11.00 to 24.00", "| 2.00 |", "| 7.00 |", "| 14.50 |"):
            self.assertIn(value, self.proof)

    def test_no_bare_percentage_and_no_words_we_do_not_use(self):
        for sentence in self.sentences:
            with self.subTest(sentence=sentence):
                if "%" in sentence:
                    self.assertIn("between", sentence)
                self.assertNotRegex(sentence.lower(), r"tracks|locates|pinpoints|which side|live on the kit")

    def test_what_was_only_tuned_on_has_no_number(self):
        for sentence in self.sentences:
            self.assertNotRegex(sentence.lower(), r"walk|to the side|behind")
        self.assertIn("seen once and used for tuning", self.text)


if __name__ == "__main__":
    unittest.main()
