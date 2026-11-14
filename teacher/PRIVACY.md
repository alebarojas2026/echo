# No image or video output

`python -m pytest teacher/tests/test_privacy.py` scans repository Python,
JavaScript/TypeScript and shell source. The check detects common image/video
writer calls, Python import aliases, Pillow image saves, direct frame writes,
media-file writes and external video encoders. Numeric labels, calibration,
model persistence, camera reads and in-memory display remain allowed.

The test scans every source folder, excluding dependencies, generated build
files and virtual environments. Browser screenshot calls remain permitted for
the `web/tests/` exception in AGENTS.md. Fixtures for the guard are source strings;
they never execute a writer or create an image.

This is a static regression guard, not a proof about arbitrary dynamic code or
third-party packages. New persistence APIs must be added to the guard and its
tests during review. The installed camera brick and its container configuration
also need the board privacy check; repository source cannot establish their
runtime disk behavior.
