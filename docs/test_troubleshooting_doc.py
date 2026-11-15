import unittest
from pathlib import Path


CUT = ("camera", "beacon", "cardboard arm", "east", "west", "twelve core links", "bluetooth", "s-home",
       "router_home", "tray", "strip", "model.trained", "training", "lean aside", "?src=ws", "esp32")


class TroubleshootingDocTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = Path(__file__).with_name("troubleshooting.md").read_text(encoding="utf-8")
        cls.lower = cls.text.lower()

    def test_fast_checks_follow_demo_dependencies(self):
        checks = ("1. **page:**", "2. **source:**", "3. **feed:**", "4. **line:**", "5. **baseline:**",
                  "6. **record:**")
        positions = [self.lower.index(check) for check in checks]
        self.assertEqual(positions, sorted(positions))

    def test_contract_failure_states_are_not_treated_as_empty(self):
        for phrase in ("`no data` means the state feed is stale",
                       "`sensor blind` means the wi-fi line is not reporting",
                       "neither state means that the spot is empty", "decisions stay null",
                       "alert timers pause", "expected state if pi b loses power; stop judging before recovery"):
            self.assertIn(phrase, self.lower)

    def test_demo_recovery_paths_are_covered(self):
        for heading in ("## The page does not load", "## The screen says `NO DATA`",
                        "## The screen says `SENSOR BLIND`",
                        "## Nobody is found, or somebody is found in an empty spot",
                        "## A witness is silent, or none is listed", "## \"What happened?\" is slow or wrong",
                        "## A no-movement alert will not clear", "## Proof values show `__`",
                        "## Return to a known state"):
            self.assertIn(heading, self.text)

    def test_roles_and_public_language_stay_clear(self):
        for phrase in ("the pis run no model", "on the dragonwing cpu", "needs alexander:",
                       "no-movement alert", "a walk straight through is not reliably seen",
                       "a few seconds", "at desk height"):
            self.assertIn(phrase, self.lower)

    def test_laptop_path_recovery_names_links_and_ports(self):
        for phrase in ("laptop is joined to the pi hotspot", "sudo bash pi/eth.sh", "sudo bash board/eth.sh",
                       "websocket port `8765`", "http port `8080`", "python3 -m pi.check --node pi5b",
                       "192.168.77.2:5600", "its address comes from dhcp"):
            self.assertIn(phrase, self.lower)

    def test_signing_recovery_never_moves_a_private_key(self):
        for phrase in ("journalctl -u radio-sight-witness", "python3 -m pi.witness --pubkey",
                       "never use `--force`", "never copy a private key off a pi",
                       "the record keeps counting while a witness is silent"):
            self.assertIn(phrase, self.lower)

    def test_check_in_and_proof_blanks(self):
        for phrase in ("step fully out of the line and back", "a lean does not count",
                       "keep the value as `__`", "numbers-to-say.md",
                       "take the baseline with the spot empty",
                       "set pi b's clock before anything else", "`pi5>pi5b:wifi` is listed and updating"):
            self.assertIn(phrase, self.lower)

    def test_cut_parts_are_absent(self):
        for cut in CUT:
            self.assertNotIn(cut, self.lower, cut)


if __name__ == "__main__":
    unittest.main()
