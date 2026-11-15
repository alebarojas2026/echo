"""Every timing and threshold of the people rules, in one place.

These are the numbers that decide when somebody "arrived", when an armed space was entered,
and when a person standing still stops counting as still. The defaults are the values in
CONTRACTS.md section 6; a tuned value is a one-line change to a default below. Nothing else
in brain/ carries its own copy.

    setting               rule (section 6)                                   default
    smooth_decisions      Alert: zone and kind are the majority of this many  10 (1 s)
    smooth_majority       ... and a value needs this many of them             6
    moving_run            Alert: "moving" decisions in a row before the       5 (0.5 s)
                          still timer resets
    intrusion_decisions   Armed: a person appears when present for the        10 (1 s)
    intrusion_majority    majority of the last N decisions                    6
    zone_hold             the brain's own: decisions in a row before enter,   5 (0.5 s)
                          exit or zone_change is said
    motion_links          which links' features decide moving / still         null = every link
                          (takes effect at the next train)
    tamper_silent_ms      Tamper: a node is silent when none of its links     3000
                          has had a reading for this long
    tamper_clear_ms       ... and back when they all have for this long       2000

Three more make a fixed dB number give way to the link's own quiet level where that is larger.
A link's quiet level is the std of its 0.5 s means over the baseline capture (quiet_db in
baseline.json): about 0.2 dB on the Wi-Fi links and 1 to 3 dB on the Bluetooth links, measured
on the kit. 0 switches a setting off, and the rule then uses the contract's number alone.

    steady_x_quiet        Link health, the jump rule: a drop is steady when   0 (0.8 dB only)
                          the std of its 0.5 s means is under 0.8 dB, or
                          under this x the link's quiet level
    checkin_x_quiet       Check-in: no other link may change by over 3 dB,    0 (3 dB only)
                          or by over this x its quiet level
    settle_x_quiet        Router: after router_home a pi5 link sits within    0 (1 dB only)
                          1 dB of base, or within this x its quiet level
                          (the same for the drift event)

One number of these rules is not here because the contract puts it in radio/nodes.json: how
long an armed space waits before an appearance is an intrusion, armed.hold_s (3 s when the file
has none). brain.settings.hold_s(nodes) reads it.

A decision is one classifier answer; there are 10 a second (section 6, Windows: 0.1 s hop).

To try other values without editing this file (a sweep, or brain/replay.py on a recording),
name a JSON file in RADIO_SIGHT_SETTINGS, or pass Settings to Brain:

    {"moving_run": 8, "motion_links": ["east>unoq:ble", "west>unoq:ble"]}

A name that is not a setting, or a value of the wrong kind, is an error at start: a typo
must never run as the defaults in silence.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields, replace
from typing import Optional, Tuple


@dataclass(frozen=True)
class Settings:
    smooth_decisions: int = 10
    smooth_majority: int = 6
    moving_run: int = 5
    intrusion_decisions: int = 10
    intrusion_majority: int = 6
    zone_hold: int = 5
    motion_links: Optional[Tuple[str, ...]] = None
    tamper_silent_ms: int = 3000
    tamper_clear_ms: int = 2000
    steady_x_quiet: float = 0.0
    checkin_x_quiet: float = 0.0
    settle_x_quiet: float = 0.0

    def __post_init__(self):
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name == "motion_links":
                if value is None:
                    continue
                if isinstance(value, str) or not value or not all(isinstance(k, str) for k in value):
                    raise ValueError("motion_links is a list of link ids, or null for every link")
                object.__setattr__(self, f.name, tuple(value))
            elif f.name.endswith("_x_quiet"):
                if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 20:
                    raise ValueError(f"{f.name} must be a number from 0 (off) to 20 (got {value!r})")
                object.__setattr__(self, f.name, float(value))
            elif not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{f.name} must be a whole number, 1 or more (got {value!r})")
        for part, whole in (("smooth_majority", "smooth_decisions"), ("intrusion_majority", "intrusion_decisions")):
            if not getattr(self, whole) / 2 < getattr(self, part) <= getattr(self, whole):
                raise ValueError(f"{part} must be more than half of {whole} and at most {whole}")

    def with_(self, **changes) -> "Settings":
        """A copy with some values changed. An unknown name is an error."""
        names = [f.name for f in fields(self)]
        unknown = sorted(set(changes) - set(names))
        if unknown:
            raise ValueError(f"not a setting: {', '.join(unknown)} (the settings are {', '.join(names)})")
        return replace(self, **changes)

    def as_dict(self) -> dict:
        out = asdict(self)
        out["motion_links"] = None if self.motion_links is None else list(self.motion_links)
        return out


DEFAULT = Settings()   # the contract's values
HOLD_S = 3.0           # section 6, Armed: armed.hold_s when nodes.json has none
DECISIONS_PER_S = 10   # section 6, Windows: a 0.1 s hop


def hold_s(nodes: Optional[dict]) -> float:
    """armed.hold_s from a parsed nodes.json: how long somebody must stay, after appearing in an
    armed space, to be an intrusion and not a passer-by. 3 s when the file doesn't say."""
    value = ((nodes or {}).get("armed") or {}).get("hold_s", HOLD_S)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 60:
        raise ValueError(f"armed.hold_s in nodes.json must be a number of seconds from 0 to 60 (got {value!r})")
    return float(value)


def load(path=None) -> Settings:
    """The defaults, changed by the JSON file in `path` or in RADIO_SIGHT_SETTINGS when there is one."""
    path = path or os.environ.get("RADIO_SIGHT_SETTINGS")
    if not path:
        return DEFAULT
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    if not isinstance(doc, dict):
        raise ValueError(f"{path}: a settings file is one JSON object")
    return DEFAULT.with_(**doc)
