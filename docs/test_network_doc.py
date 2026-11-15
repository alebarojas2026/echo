import re
import unittest
from pathlib import Path


NETWORK_DOC = Path(__file__).with_name("network.md")

# Parts that were cut from the product (the Bluetooth readers are named once, as deciding nothing).
CUT = ("camera teacher", "camera lesson", "dead-zone", "dead zone", "beacon", "esp32",
       "twelve core classifier links", "east and west", "radio sight", "setup labels")
ADDRESSES = {"192.168.77.1", "192.168.77.2", "192.168.77.0", "10.42.0.1", "10.42.0.0",
             "127.0.0.1", "0.0.0.0"}


class NetworkDocTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = NETWORK_DOC.read_text(encoding="utf-8")
        cls.lower = cls.text.lower()

    def test_contract_endpoints_are_documented(self):
        for endpoint in (
            "192.168.77.1",
            "192.168.77.2",
            "10.42.0.1",
            "0.0.0.0:5600",
            "127.0.0.1:5601",
            "127.0.0.1:5602",
            "ws://192.168.77.2:8765/ws",
            "http://192.168.77.2:8080",
            "http://127.0.0.1:8091",
        ):
            self.assertIn(endpoint, self.text)

    def test_roles_and_network_paths_are_clear(self):
        self.assertTrue(self.text.startswith("# How Echo connects"))
        for phrase in (
            "direct ethernet cable",
            "5 ghz wi-fi hotspot",
            "message bus",
            "websocket",
            "one ethernet cable",
            "do not copy files or bundles over the hotspot",
            "neither pi runs a model",
            "nothing needs the internet",
        ):
            self.assertIn(phrase, self.lower)
        self.assertNotIn("browser in kiosk mode", self.lower)

    def test_every_message_has_a_row(self):
        table = self.text.split("## Which message goes where", 1)[1].split("\n## ", 1)[0]
        for message in ("`rssi`", "`chain_head`", "`chain_sub`", "`chain_witness`",
                        "State and events", "Pages, Ask"):
            self.assertIn(message, table)
        self.assertIn("25 a second", table)
        self.assertEqual(table.count("every 5 s"), 3)

    def test_pages_are_listed(self):
        for page in ("http://192.168.77.2:8080/`", "/engine/", "/phone/"):
            self.assertIn(page, self.text)

    def test_bring_up_and_browser_ports_are_explicit(self):
        for phrase in (
            "sudo bash pi/eth.sh",
            "sudo bash board/eth.sh",
            "sudo bash pi/ap.sh",
            "sudo bash radio/wifi_join.sh",
            "python -m pi.radio_node --node pi5b",
            "python3 -m pi.witness --init",
            "http port `8080` and websocket port `8765`",
            "baseline with the spot empty",
        ):
            self.assertIn(phrase, self.lower)

    def test_private_device_identifiers_are_absent(self):
        self.assertIsNone(
            re.search(r"\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b", self.text, re.I)
        )
        self.assertNotIn("mac address", self.lower)
        self.assertLessEqual(set(re.findall(r"\b\d+\.\d+\.\d+\.\d+\b", self.text)), ADDRESSES)

    def test_pi_b_path_is_explicit(self):
        for phrase in (
            "pi b has no cable",
            "no address for it is written into the repository",
            "192.168.77.2:5600",
            "pi a forwards hotspot traffic onto the cable",
            "the private key never leaves the pi",
        ):
            self.assertIn(phrase, self.lower)

    def test_cut_parts_are_absent(self):
        for phrase in CUT:
            self.assertNotIn(phrase, self.lower)
        self.assertEqual(self.lower.count("bluetooth"), 1)
        self.assertIn("they decide nothing", self.lower)
        self.assertIn("no camera and no microphone", self.lower)


if __name__ == "__main__":
    unittest.main()
