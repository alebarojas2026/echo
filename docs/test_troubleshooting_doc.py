import unittest
from pathlib import Path


GUIDE = Path(__file__).with_name("troubleshooting.md")


class TroubleshootingDocTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = GUIDE.read_text(encoding="utf-8")
        cls.lower = cls.text.lower()

    def test_fast_checks_follow_demo_dependencies(self):
        checks = (
            "1. **page:**",
            "2. **source:**",
            "3. **feed:**",
            "4. **radio health:**",
            "5. **router:**",
            "6. **model:**",
        )
        positions = [self.lower.index(check) for check in checks]
        self.assertEqual(positions, sorted(positions))

    def test_contract_failure_states_are_not_treated_as_empty(self):
        for phrase in (
            "`no data` means the state feed is stale",
            "`sensor blind` means at least one classifier link is unhealthy",
            "neither state means that the room is empty",
            "predictions stay null",
            "alert timers pause",
            "a steady below-baseline drop is treated as an object",
            "not a broken link",
        ):
            self.assertIn(phrase, self.lower)

    def test_demo_recovery_paths_are_covered(self):
        for heading in (
            "## The page does not load",
            "## The screen says `NO DATA`",
            "## The screen says `SENSOR BLIND`",
            "## The camera is off or stalled",
            "## Baseline or training will not complete",
            "## Predictions disappear after moving the router",
            "## A no-movement alert will not clear",
            "## Proof values show `__`",
        ):
            self.assertIn(heading, self.text)

    def test_roles_and_public_language_stay_clear(self):
        for phrase in (
            "the pi runs no model",
            "on the dragonwing cpu",
            "setup labels only",
            "no image or video",
            "works behind a curtain",
            "needs alexander:",
        ):
            self.assertIn(phrase, self.lower)

    def test_laptop_path_recovery_names_links_and_ports(self):
        for phrase in (
            "laptop is joined to the pi hotspot",
            "sudo bash pi/eth.sh",
            "sudo bash board/eth.sh",
            "websocket port `8765`",
            "http port `8080`",
        ):
            self.assertIn(phrase, self.lower)

    def test_router_and_calibration_recovery_match_v2(self):
        for phrase in (
            "remove the tray",
            "return the pi to `s-home` before sending `router_home`",
            "automatic baseline",
            "label mode is `off`",
            "keep the square clear",
            "redo the camera calibration",
            "keep the value as `__`",
        ):
            self.assertIn(phrase, self.lower)

        recovery = self.lower.split("## predictions disappear after moving the router", 1)[1]
        steps = (
            "remove the tray",
            "object marker and static change clear",
            "return the pi to `s-home`",
            "send `router_home`",
            "send `reset`",
        )
        positions = [recovery.index(step) for step in steps]
        self.assertEqual(positions, sorted(positions))

    def test_no_movement_recovery_explains_smoothed_decisions(self):
        for phrase in (
            "the still timer uses smoothed decisions",
            "brief motion noise does not reset it",
            "five moving decisions in a row",
            "the majority of the last ten decisions",
        ):
            self.assertIn(phrase, self.lower)


if __name__ == "__main__":
    unittest.main()
