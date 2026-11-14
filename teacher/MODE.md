# Host-to-App Lab label mode

The brain's `--mode-file` / `TEACHER_MODE_FILE` must name the host side of a
directory mounted into the teacher container. The teacher's `TEACHER_MODE_FILE`
names the same file inside that mount. Initialize its numeric-free text to `off`.
The screen sends the unchanged v2 label_mode command to the brain; the brain
writes person/object/off and the teacher reads it on every processed frame.
No restart or timer-derived empty label is involved. If the file is missing or
invalid the adapter emits no label and retries on the next real result.

The host round-trip test sends the actual screen command through Brain.on_cmd,
uses a shared temporary file and a fake processed frame, and verifies the serialized
label within 1 s for every mode. It also tests recovery from a missing file.
Tests skip when the brain live-loop package is not yet available.

Alexander must confirm the directory bind mount and permissions on the board:
change each screen mode and inspect the next label message. It must carry the new
mode within 1 s at the expected 5–10 Hz frame rate, including explicit empty frames.
