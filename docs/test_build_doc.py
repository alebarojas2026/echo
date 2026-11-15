import unittest
from pathlib import Path


BUILD = Path(__file__).with_name("build.md")


class BuildDocTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = BUILD.read_text(encoding="utf-8")
        cls.lower = cls.text.lower()

    def test_required_parts_are_listed(self):
        for part in (
            "arduino uno q",
            "two raspberry pi 5",
            "powered usb-c hub with ethernet and power delivery",
            "usb webcam",
            "two esp32-s3 boards",
            "laptop for the demo browser",
            "tape for the final presentation-hour layout",
            "three `25 cm` boxes",
            "two cardboard arms",
            "string knotted at `0`, `0.5`, `0.8`, `1.1`, and `1.6 m`",
        ):
            self.assertIn(part, self.lower)

    def test_setup_steps_are_in_safe_order(self):
        steps = (
            "### finish internet installs first",
            "### bring up the direct ethernet link",
            "### mark the layout with loose markers",
            "### calibrate the setup camera",
            "### start pi a's private hotspot",
            "### run the signal test",
        )
        positions = [self.lower.index(step) for step in steps]
        self.assertEqual(positions, sorted(positions))

    def test_presentation_hour_requires_fresh_setup(self):
        for phrase in (
            "tape the final floor marks and cardboard arms only now",
            "redo the camera calibration",
            "redo the `20 s` baseline and training",
            "every node on its assigned mark at `1.0 m`",
        ):
            self.assertIn(phrase, self.lower)

    def test_roles_and_network_reference_are_clear(self):
        for phrase in (
            "all learned work runs locally",
            "it runs no model",
            "laptop browser shows the local interface",
            "do not copy files or bundles over the hotspot",
            "sudo bash pi/eth.sh",
            "sudo bash board/eth.sh",
            "sudo bash pi/ap.sh",
            "sudo bash radio/wifi_join.sh",
            "http://192.168.77.2:8080/?src=ws",
            "[network guide](network.md)",
            "do not plan around venue wi-fi",
            "no image or video is saved",
            "all twelve core links",
            "two wi-fi and ten bluetooth",
            "baseline {keep_model: true}",
            "camera unplugged",
        ):
            self.assertIn(phrase, self.lower)

        self.assertNotIn("drives the display", self.lower)

    def test_east_and_west_beacons_are_not_phones(self):
        for phrase in (
            "east and west bluetooth beacons",
            "east and west esp32-s3 beacons on the tips",
            "phones are not used as beacons",
        ):
            self.assertIn(phrase, self.lower)

        self.assertNotIn("beacon phones", self.lower)

    def test_desk_strip_layout_replaces_the_square(self):
        for phrase in (
            "`1.6 x 0.6 m` sensing strip",
            "pi a at `s-home`",
            "pi b to the same hotspot",
            "its address comes from dhcp",
            "left/right split",
        ):
            self.assertIn(phrase, self.lower)

        self.assertNotIn("the " + "square", self.lower)


if __name__ == "__main__":
    unittest.main()
