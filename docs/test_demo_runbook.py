import unittest
from pathlib import Path


RUNBOOK = Path(__file__).with_name("demo-runbook.md")
BEATS = (
    "found you",
    "teach the room",
    "camera unplug",
    "still follows",
    "arm the space",
    "intrusion alert",
    "ask the room",
    "proof",
)


class DemoRunbookTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = RUNBOOK.read_text(encoding="utf-8")
        cls.lower = cls.text.lower()

    def test_required_stages_are_present_and_desk_round_is_first(self):
        for heading in (
            "Preflight",
            "Baseline and training",
            "Three-minute desk round",
            "Camera-unplug proof",
            "Five-minute finalist round",
            "Proof check",
            "Recovery",
            "After the demo",
        ):
            self.assertIn(f"## {heading}", self.text)
        self.assertLess(
            self.text.index("## Three-minute desk round"),
            self.text.index("## Five-minute finalist round"),
        )

    def test_primary_beats_are_in_order(self):
        desk = self.lower.split("## three-minute desk round", 1)[1].split(
            "## camera-unplug proof", 1
        )[0]
        positions = []
        for beat in BEATS:
            marker = f"**{beat}:**"
            self.assertIn(marker, desk)
            positions.append(desk.index(marker))
        self.assertEqual(positions, sorted(positions))

    def test_contract_v2_failure_states_are_distinct(self):
        self.assertIn("### `NO DATA`", self.text)
        self.assertIn("### `SENSOR BLIND`", self.text)
        self.assertIn("last state is stale", self.lower)
        self.assertIn("required classifier link is unhealthy", self.lower)
        self.assertIn("never call it empty", self.lower)

    def test_preflight_uses_the_live_laptop_path_and_layout(self):
        for phrase in (
            "ask alexander to run",
            "sudo bash pi/eth.sh",
            "sudo bash board/eth.sh",
            "sudo bash pi/ap.sh",
            "sudo bash radio/wifi_join.sh",
            "join the demo laptop",
            "http://192.168.77.2:8080/?src=ws",
            "ws://192.168.77.2:8765/ws",
            "radio/nodes.json",
            "do not copy files or bundles",
        ):
            self.assertIn(phrase, self.lower)

    def test_camera_unplug_is_continuous_and_radio_stays_live(self):
        proof = self.lower.split("## camera-unplug proof", 1)[1].split(
            "## five-minute finalist round", 1
        )[0]
        for phrase in (
            "live laptop screen and camera cable visible together",
            "unplug the camera",
            "teacher` becomes null",
            "radio state continues to update",
            "source remains `live`",
        ):
            self.assertIn(phrase, proof)

    def test_unshipped_beats_fail_closed(self):
        desk = self.lower.split("## three-minute desk round", 1)[1].split(
            "## camera-unplug proof", 1
        )[0]
        self.assertIn("only if the current build exposes", desk)
        self.assertIn("only if the current build can answer", desk)
        self.assertIn("do not improvise an answer", desk)
        self.assertIn("go directly to **proof**", desk)

    def test_finalist_only_features_keep_their_safety_checks(self):
        finalist = self.lower.split("## five-minute finalist round", 1)[1].split(
            "## if asked", 1
        )[0]
        for phrase in (
            "whole-hall view",
            "no-movement alert",
            "checkin-toast",
            "tray and router advice",
            "pi5>unoq:wifi",
            "drop_db` of at least `3 db`",
            "advice does not appear without that live drop",
            "advice-text",
            "router_moved",
            "fact-based local recap",
            "game",
        ):
            self.assertIn(phrase, finalist)

    def test_finish_restores_optional_hardware_before_reset(self):
        finish = self.lower.split("## finish the live demo", 1)[1].split(
            "## proof check", 1
        )[0]
        positions = [
            finish.index("remove it"),
            finish.index("object marker and static change to clear"),
            finish.index("return the pi to its home spot"),
            finish.index("send `router_home`"),
            finish.index("send `reset`"),
        ]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("alexander handles the tray and pi", finish)

    def test_narrator_warmup_never_blocks_the_demo(self):
        for phrase in (
            "warm its local model in the background",
            "the template path remains available",
            "warms its normal sentence prompt again in the background after the recap",
            "do not hold the next judge for that warmup",
            "template recap",
        ):
            self.assertIn(phrase, self.lower)

    def test_proof_values_never_get_estimated(self):
        for phrase in (
            "lesson time: __ s",
            "images stored: __",
            "bytes sent outside local network: __",
            "json `null` must render as `__`",
            "never replace it with an estimate",
        ):
            self.assertIn(phrase, self.lower)


if __name__ == "__main__":
    unittest.main()
