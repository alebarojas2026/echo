import re
import unittest
from pathlib import Path


NETWORK_DOC = Path(__file__).with_name("network.md")


class NetworkDocTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = NETWORK_DOC.read_text(encoding="utf-8")
        cls.lower = cls.text.lower()

    def test_contract_v2_endpoints_are_documented(self):
        for endpoint in (
            "192.168.77.1",
            "192.168.77.2",
            "10.42.0.1",
            "5600",
            "5601",
            "8765",
            "8080",
            "8091",
        ):
            self.assertIn(endpoint, self.text)

    def test_roles_and_network_paths_are_clear(self):
        for phrase in (
            "direct ethernet cable",
            "5 ghz wi-fi hotspot",
            "message bus",
            "websocket",
            "demo screen",
            "camera teacher",
        ):
            self.assertIn(phrase, self.lower)

    def test_private_device_identifiers_are_absent(self):
        self.assertIsNone(
            re.search(r"\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b", self.text, re.I)
        )
        for internal_name in ("unoq", "pi5", "east", "west"):
            self.assertNotIn(internal_name, self.lower)


if __name__ == "__main__":
    unittest.main()
