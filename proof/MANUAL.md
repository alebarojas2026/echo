# Sourced board measurements

After scoring at the current commit, enter a power reading with:
`python -m proof.manual --mode idle --watts <measured-W> --duration-s <at-least-300> --source '<meter model and method>' --measured-at <ISO-time>`.
Repeat for teaching and radio_only. Never use example numbers as readings.

Alexander starts counters with `sudo board/egress.sh start`, runs the intended
measurement interval, then runs on the board:
`sudo python -m proof.manual --egress --egress-duration-s <actual-seconds> --egress-source '<method and full rehearsal interval>' --measured-at <ISO-time>`.
The command verifies the UNO Q identity and executes `board/egress.sh count`
itself; an arbitrary saved text file is not accepted. The output is a strict
integer; failed counter commands are rejected. Zero egress is valid, zero power
is not. The script does not start/reset counters.
Both `ip -4 route show default` and `ip -6 route show default` must be empty.
This measures the counter interval, not all historical traffic. Keep the board
on our own network; traffic to the local laptop and phone is allowed.

Immediately after a full lesson, before unplugging the camera/stopping its app:
`sudo python -m proof.manual --images --teacher-container <actual-running-name-or-id-from-docker-ps> --measured-at <ISO-time>`.
The teacher container must still be running. The audit
requires `data/`, `teacher/applab/`, the checkout owner's `~/ArduinoApps` (override
with `--apps-dir <actual-apps-folder>`), and every teacher container host mount.
Missing/unreadable folders, missing mount sources, and unavailable Docker fail;
none are treated as zero. Do not create an empty replacement for a missing folder.

The suffix list comes from `teacher/privacy.py`. Host symlinks are followed with
loop protection; hard links and overlapping mounts count once. Library folders
and assets already present before the lesson are included, so any such images
also produce a nonzero result. Docker inspection discovers mounts; a read-only
Python walk inside the container counts its whole filesystem, except virtual
`/proc`, `/sys`, `/dev` and host mounts already counted. Docker exec needs a
running container and Python 3; if either is unavailable the audit fails. No pixels
or archives are read, extracted or written. This cannot prove that a file was
never written and deleted between audits.

Once the live privacy meter is deployed, add `--check-meter` to require a fresh
`/privacy` image count equal to this audit. A missing, stale or disagreeing meter
fails the command. Without that flag, the report never claims agreement. This
compares image counts only; the live meter's separate egress counter is not reset
or claimed to agree. A filtered live meter can disagree with this full audit;
never replace the result with zero or claim agreement unless it was observed.

Run `python -m proof.render_table --output PROOF.md` to fill the two privacy rows.
The local `proof.manual.jsonl` supplies their own date, scope and interval; without
that evidence the date and N stay `__`. Optional image-audit metadata is served
only when the current proof schema accepts it (contract #735). Counts use the
existing frozen scalar fields. Privacy can be the first measurement: every
unmeasured field starts null. Keep local folder/container identifiers out of git.

Power requires at least 300 s per mode and a positive finite reading. Datasheet,
specification, rated, typical and URL sources are refused; use actual meter data.
No measurement is accepted without its source. Values from another commit or
power readings with a different meter source are refused. Existing proof fields
and their date remain intact. Each manual reading's actual date and source are
also recorded in a local `proof.manual.jsonl` evidence log; no device identifiers
or meter serial numbers belong in committed files. No hardware is needed by tests.
