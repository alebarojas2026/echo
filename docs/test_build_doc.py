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
            "raspberry pi 5",
            "powered usb-c hub with ethernet and power delivery",
            "usb webcam",
            "two esp32-s3 boards",
            "laptop for the demo browser",
            "tape for the final presentation-hour layout",
            "stands",
        ):
            self.assertIn(part, self.lower)

    def test_setup_steps_are_in_safe_order(self):
        steps = (
            "### finish internet installs first",
            "### mark the layout with loose markers",
            "### calibrate the setup camera",
            "### start the pi's private hotspot",
            "### run the signal test",
        )
        positions = [self.lower.index(step) for step in steps]
        self.assertEqual(positions, sorted(positions))

    def test_presentation_hour_requires_fresh_setup(self):
        for phrase in (
            "tape the final floor marks only now",
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
            "[network guide](network.md)",
            "do not plan around venue wi-fi",
            "no image or video is saved",
        ):
            self.assertIn(phrase, self.lower)

        self.assertNotIn("drives the display", self.lower)

    def test_east_and_west_beacons_are_not_phones(self):
        for phrase in (
            "east and west bluetooth beacons",
            "esp32-s3 beacons at the east and west markers",
            "phones are not used as beacons",
        ):
            self.assertIn(phrase, self.lower)

        self.assertNotIn("beacon phones", self.lower)


if __name__ == "__main__":
    unittest.main()
