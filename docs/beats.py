"""The demo's beat names, in run order. The pitch, the runbook, the Devpost draft and the video
shot list must all use these names in this order; the docs tests read them from here."""

BEATS = (
    "Found you",
    "Live signal",
    "Teach the room",
    "Camera unplug",
    "Still follows",
    "Dead zone",
    "Arm the space",
    "Intrusion alert",
    "Tamper alert",
    "Ask the room",
    "Replay",
    "Incident report",
    "Proof",
)
# Never dropped, however short the visit. Dead zone is the required safety/security
# or dead-zone proof; intrusion may replace it only when the operator deliberately
# chooses that path.
CORE = ("Found you", "Camera unplug", "Dead zone", "Proof")
