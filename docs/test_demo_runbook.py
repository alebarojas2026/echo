import unittest
from pathlib import Path

from beats import BEATS


RUNBOOK = Path(__file__).with_name("demo-runbook.md")


class DemoRunbookTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = RUNBOOK.read_text(encoding="utf-8")
        cls.lower = cls.text.lower()

    def test_judge_day_preparation_and_freeze_are_explicit(self):
        steps = ("Power up", "Set the board's clock", "commit the deploy printed", "radio.use_layout gate",
                 "Capture the empty baseline", "scripts/demo_check.py", "/chain", "outside the team",
                 "real local model")
        positions = [self.text.index(step) for step in steps]
        self.assertEqual(positions, sorted(positions))
        for phrase in ("**From Sunday 9:30 AM", "**Before any restart", "board/deploy.sh <last-good-tag>",
                       "board/push-web.sh --back", "No webcam is plugged in",
                       "The baseline comes first, before anything is judged"):
            self.assertIn(phrase, self.text)

    def test_required_stages_are_present(self):
        for heading in ("At the desk", "Preflight", "Three-minute desk round", "Five-minute finalist round",
                        "Proof check", "Recovery", "After the demo"):
            self.assertIn(f"## {heading}", self.text)

    def test_at_the_desk_assigns_roles_and_failure_words(self):
        at_desk = self.lower.split("## at the desk", 1)[1].split("## preflight", 1)[0]
        for role in ("talker", "operator", "hardware", "spotter"):
            self.assertIn(f"| {role} |", at_desk)
        for phrase in ("that's the honest failure. the wi-fi line stopped reporting",
                       "the screen lost the board's feed",
                       "it needs a few seconds on the line",
                       "the language model on this board is tiny"):
            self.assertIn(phrase, at_desk)
        self.assertIn("at least two people at the desk", at_desk)
        self.assertNotIn("not ready", self.lower)

    def test_judge_day_screens_join_the_kits_own_wifi(self):
        screens = self.text.split("### Judge-day screens", 1)[1].split("## Preflight", 1)[0]
        for phrase in ("every one of them joins the kit's own Wi-Fi directly",
                       "`http://192.168.77.2:8080/`", "`http://192.168.77.2:8080/engine/`",
                       "`http://192.168.77.2:8080/phone/`", "A looping slide",
                       "one page per device, full screen, in the front tab",
                       "sleep and dimming off", "has no internet, which is expected",
                       "press `P`, click the desk the board is on", "press `Enter`", "Saved: Row N, block M"):
            self.assertIn(phrase, screens)

    def test_contract_v2_failure_states_are_distinct(self):
        self.assertIn("### `NO DATA`", self.text)
        self.assertIn("### `SENSOR BLIND`", self.text)
        self.assertIn("last state is stale", self.lower)
        self.assertIn("neither state means the spot is empty", self.lower)

    def test_primary_beats_are_in_order(self):
        beats = [f"**{beat.lower()}**" for beat in BEATS]
        positions = [self.lower.index(beat) for beat in beats]
        self.assertEqual(positions, sorted(positions))

    def test_timed_round_has_speakers_actions_and_screens(self):
        desk = self.text.split("## Three-minute desk round", 1)[1].split("## Five-minute finalist round", 1)[0]
        for phrase in ("0:00–0:30", "0:30–1:00", "1:00–1:25", "1:25–2:00", "2:00–2:30", "2:30–3:00",
                       "Speaker and actions", "Screen and gate"):
            self.assertIn(phrase, desk)
        for phrase in ("cut the Tamper alert first", "Keep Found you",
                       "at least one of Intrusion alert or What happened", "do not stage it"):
            self.assertIn(phrase, desk)

    def test_the_round_is_the_witness_demo(self):
        desk = self.lower.split("## three-minute desk round", 1)[1].split("## five-minute finalist round", 1)[0]
        for phrase in ("unplugs pi b", "that witness silent", "taps \"what happened?\"", "presses prove it",
                       "the check naming the altered record", "word for word from numbers-to-say.md",
                       "set pi b's clock, then take the empty baseline before the next judge",
                       "stands still until the no-movement alert, then steps aside and back", "check-in received"):
            self.assertIn(phrase, desk)

    def test_preflight_uses_the_live_laptop_path(self):
        for phrase in ("ask alexander to run", "sudo bash pi/eth.sh", "sudo bash board/eth.sh",
                       "sudo bash pi/ap.sh", "sudo bash radio/wifi_join.sh", "join the demo laptop",
                       "http://192.168.77.2:8080/", "ws://192.168.77.2:8765/ws", "radio/nodes.json",
                       "do not copy files or bundles"):
            self.assertIn(phrase, self.lower)

    def test_one_spot_kit_and_check_in_are_explicit(self):
        for phrase in ("power pi b", "three devices for one spot", "pi b about a metre away at desk height",
                       "wi-fi from pi a to pi b is the only line that decides", "steps aside and back",
                       "no-movement alert", "json `null` must render as `__`",
                       "never a bare percentage", "private key stays on that pi",
                       "pi b's clock resets whenever it loses power", "secure pi b's power cable",
                       "unplugging it is a power loss: ask alexander to set pi b's clock before the baseline",
                       "going back is one command on each device", "role=pib", "-44 dbm"):
            self.assertIn(phrase, self.lower)

    def test_narrator_warmup_never_blocks_the_demo(self):
        for phrase in ("warm its local model in the background", "the template path remains available",
                       "do not hold the next judge for that warmup"):
            self.assertIn(phrase, self.lower)

    def test_nothing_cut_from_the_product_is_in_the_runbook(self):
        for cut in ("camera lesson", "unplug the camera", "teacher", "lesson", "dead zone", "dead-zone", "beacon", "bluetooth", "move the router",
                    "taught by", "lean aside", "passed by", "walk-through", "walked through", "recording of the real board",
                    "tracks", "locates", "pinpoints", "blockchain", "unhackable", "tamper-proof"):
            self.assertNotIn(cut, self.lower)


if __name__ == "__main__":
    unittest.main()
