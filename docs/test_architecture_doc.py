import re
import unittest
from pathlib import Path


ARCHITECTURE = Path(__file__).with_name("architecture.md")


class ArchitectureDocTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = ARCHITECTURE.read_text(encoding="utf-8")
        cls.lower = cls.text.lower()

    def test_mermaid_covers_contract_data_flow(self):
        self.assertIn("```mermaid", self.text)
        for phrase in (
            "Wi-Fi RSSI reader",
            "Bluetooth HCI reader",
            "Camera teacher",
            "Message bus",
            "Brain",
            "Router advisor",
            "Narrator",
            "llama-server",
            "LED grid",
            "Laptop browser",
        ):
            self.assertIn(phrase, self.text)

    def test_contract_v2_ports_are_exact(self):
        for endpoint in (
            "UDP 0.0.0.0:5600",
            "UDP 127.0.0.1:5601",
            "127.0.0.1:5600",
            "192.168.77.2:5600",
            "msgpack-rpc-router:5600",
            "ws://192.168.77.2:8765/ws",
            "http://192.168.77.2:8080",
            "http://127.0.0.1:8091",
        ):
            self.assertIn(endpoint, self.text)

    def test_pi_radio_role_is_bluetooth_only(self):
        self.assertIn(
            "Bluetooth beacon S and east/west readings",
            self.text,
        )
        self.assertNotIn("Wi-Fi and Bluetooth readings", self.text)

    def test_advisor_is_drawn_inside_brain(self):
        brain = re.search(
            r'subgraph BRAIN\["Brain"\](.*?)\n        end',
            self.text,
            re.DOTALL,
        )
        self.assertIsNotNone(brain)
        self.assertIn('ADVISOR["Router advisor"]', brain.group(1))

    def test_compute_and_privacy_boundaries_are_clear(self):
        for phrase in (
            "all trained models and learned decisions run on the uno q's dragonwing cpu",
            "the pi provides network and radio functions, routes the laptop browser to the board, and runs no model",
            "the camera teacher is for setup labels only and saves no image or video",
            "the arduino router bridge carries that small command",
            "not venue wi-fi or a cloud service",
        ):
            self.assertIn(phrase, self.lower)

        self.assertNotIn("pi-driven display", self.lower)
        self.assertIn("http://192.168.77.2:8080/?src=ws", self.lower)
        self.assertIn("ws://192.168.77.2:8765/ws", self.lower)


if __name__ == "__main__":
    unittest.main()
