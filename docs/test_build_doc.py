import unittest
from pathlib import Path


CUT = ("webcam", "esp32", "beacon", "cardboard arm", "left/right", "twelve core links", "bluetooth",
       "s-home", "sensing strip", "five nodes", "train on the uno q", "dead zone", "radio x-ray")


class BuildDocTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = Path(__file__).with_name("build.md").read_text(encoding="utf-8")
        cls.lower = cls.text.lower()

    def test_required_parts_are_listed(self):
        for part in ("arduino uno q", "two raspberry pi 5", "powered usb-c hub with ethernet and power delivery",
                     "laptop for the demo browser", "a phone for the alarm page",
                     "tape for the final presentation-hour layout"):
            self.assertIn(part, self.lower)
        self.assertIn("there is no camera and no microphone on the kit", self.lower)

    def test_setup_steps_are_in_safe_order(self):
        steps = ("### finish internet installs first", "### bring up the direct ethernet link",
                 "### start pi a's private hotspot", "### choose the layout before building the page",
                 "### set up the signing on each pi", "### set the clocks", "### run the signal test",
                 "### take the baseline", "### open the pages")
        positions = [self.lower.index(step) for step in steps]
        self.assertEqual(positions, sorted(positions))

    def test_three_devices_and_one_spot(self):
        for phrase in ("uno q and pi a side by side on one desk", "gap of 85 to 100 cm, at desk height",
                       "on a chair seat it fails", "pi b to the same hotspot", "its address comes from dhcp",
                       "never run `pi/install.sh --wifi-off` on pi b", "python3 -m radio.use_layout gate",
                       "`pi5>pi5b:wifi` reports 20 readings a second or more",
                       "there is no training: after the baseline the line alone gives the decision"):
            self.assertIn(phrase, self.lower)

    def test_signing_setup_keeps_the_private_key_on_the_pi(self):
        for phrase in ("python3 -m pi.witness --init", "the key is made on the pi and never leaves it",
                       "only the public key goes in the board's local key file",
                       "never paste a key into an issue, a chat or a document"):
            self.assertIn(phrase, self.lower)

    def test_roles_and_network_reference_are_clear(self):
        for phrase in ("everything runs locally", "it runs no model", "laptop browser shows the local interface",
                       "do not copy files or bundles over the hotspot", "sudo bash pi/eth.sh",
                       "sudo bash board/eth.sh", "sudo bash pi/ap.sh", "sudo bash radio/wifi_join.sh",
                       "http://192.168.77.2:8080/", "http://192.168.77.2:8080/engine/",
                       "http://192.168.77.2:8080/phone/", "[network guide](network.md)",
                       "do not plan around venue wi-fi", "pi b's clock resets whenever it loses power"):
            self.assertIn(phrase, self.lower)

    def test_presentation_hour_requires_fresh_setup(self):
        for phrase in ("tape their places only now", "redo the `20 s` baseline with the gap empty",
                       "press `p` on the judge's page", "the correct result is no decision, not \"empty.\""):
            self.assertIn(phrase, self.lower)

    def test_cut_parts_are_absent(self):
        for cut in CUT:
            self.assertNotIn(cut, self.lower)


if __name__ == "__main__":
    unittest.main()
