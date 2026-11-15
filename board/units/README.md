# Units

systemd units for every program in CONTRACTS.md section 9. Install them with `board/deploy.sh`, never by copying by hand, because the files here have placeholders.

## Install on the board
From the repo root, with the Python env already at /opt/rs/venv:
```sh
sudo board/deploy.sh --install --no-pi   # before the Pi is connected
sudo board/deploy.sh --install           # once the Pi's hotspot and the Ethernet link are up (pi/eth.sh on the Pi, board/eth.sh here)
```
Each run installs every unit, reloads systemd, enables them, and starts any that aren't running. It restarts only units whose file changed. Running it again is safe.

`--no-pi` still installs the units that need the Pi (`radio-sight-wifi-rssi` and `radio-sight-hci-scan`, the BLE scan), but stops and disables them until the Pi's hotspot and beacons are there. Run it again without `--no-pi` to start them. Once started, the Wi-Fi reader waits for the hotspot by itself (it says so once in its journal) and the BLE scan starts itself again when it goes quiet, so a Pi that comes up late or reboots needs nothing here.

Check:
```sh
systemctl list-units 'radio-sight-*'
python3 -m radio.check            # the whole radio path: ok or FAIL per line, with the fix
journalctl -u radio-sight-bus -f  # every 30 s a links: line; "<link> quiet for 3 s" the moment one stops
```

Later updates: `board/deploy.sh <tag|sha>`, as the clone's owner and without sudo (it uses sudo itself). It checks out the ref and restarts only what changed. The Pi uses the same commands; there it installs only `radio-sight-radio-node`, and runs it with or without `--no-pi`, since beacon S doesn't need the cable.

## Keep what the board learned
After the final lesson, connect the laptop through Ethernet and run
`board/keep.sh save`. Use BOARD_USER (the checkout owner), BOARD_REPO and
BOARD_HOST from the laptop's environment or .env, as for push-web. The host must
be 192.168.77.2, with no PI_HOST hop; the script checks that the laptop's route
is not Wi-Fi. KEEP_INTERFACE may name the expected Ethernet adapter. Linux
needs `ip`; macOS uses `route` and `networksetup`.
An explicit environment value wins over .env, including `PI_HOST=` to disable
a saved proxy hop for this wired command.

The dated laptop folder under data/keep/ is gitignored. It contains only
model.pkl, baseline.json, place.json, baselines.jsonl, a consistent store.db
snapshot made by Python's SQLite backup API (the same online snapshot as
`sqlite3 .backup`), the source COMMIT and checksums. No extra SQLite CLI package
is required. Recordings
are never copied. If learning changes during save, the snapshot is refused.

To recover, deploy the backup's COMMIT first, then run
`board/keep.sh restore <saved-folder>` from the wired laptop. It checks the
files and commit before stopping the brain/store, stages on the board's data
filesystem, replaces the five files with renames, starts both services, waits
up to 20 s for service/port readiness, then runs the localhost read-only demo
check. A failure while replacing files leaves
services stopped; inspect the error and retry before using the judge screen.
The SSH login must have noninteractive sudo for the service stop/start. Rehearse
one real restore after the last lesson; no successful hardware restore is
claimed by the fixture tests.

## Placeholders
| In the file | Becomes |
|---|---|
| `@REPO@` | the clone `deploy.sh` runs from (the folder above `board/`) |
| `@USER@` | that folder's owner, even under sudo. The units run as this user unless they say `User=root` |
| `@PYTHON@` | `/opt/rs/venv/bin/python`, or `$PYTHON`: `sudo PYTHON=/path/to/python board/deploy.sh --install` |

## The units
| Unit | Runs | User | Needs the Pi |
|---|---|---|---|
| radio-sight-bus | `python -m bus` | `@USER@` | |
| radio-sight-wifi-rssi | `python -m radio.wifi_rssi` | `@USER@` | yes |
| radio-sight-hci-scan | `python -m radio.hci_scan --node unoq` | root | yes |
| radio-sight-camwatch | `python -m teacher.camwatch` | `@USER@` | |
| radio-sight-brain | `python -m brain.main` | `@USER@` | |
| radio-sight-serve | `python board/serve.py` | `@USER@` | |
| radio-sight-llm | llama-server, from `narrator/llm.service` | arduino | |
| radio-sight-narrate | `python -m narrator.narrate` | `@USER@` | |
| radio-sight-store | `python -m store`: the brain's events and a summary each second, into data/sessions/store.db (what /ask, /history and /report read) | `@USER@` | |
| radio-sight-privacy | `python -m board.privacy run` | `@USER@`, with CAP_NET_ADMIN only | |
| radio-sight-clock | `python -m board.clock helper`: sets the clock when the operator asks (POST /clock), then restarts the stack in order | root | |
| radio-sight-radio-node (Pi only) | `python -m pi.radio_node` | root | no: it advertises and scans without the Ethernet link, and forwards once it's up |

A unit whose program doesn't exist yet still installs and keeps restarting until it does; `journalctl -u <unit>` shows why. If an older `llm.service` from the narrator README is installed, deploy removes it, so two model servers don't fight over port 8091.

## The privacy meter
`radio-sight-privacy` measures, every second, the image or video files on the board and the bytes it has sent out; the screen reads it from `GET /privacy` (board/serve.py, contract issue #620). `python -m board.privacy` prints one line; `python -m board.privacy reset` counts bytes from zero again and writes the time to `/var/lib/radio-sight-privacy/resets.log` and the journal.

Folders it checks for images and video (by name, and by their first bytes): every place the camera pipeline or our code could write a frame, and nothing else.
- `data/` in this checkout: everything our own code writes (sessions, the store, layout saves);
- the camera teacher's own App Lab folder, `~/ArduinoApps/<app>` from `TEACHER_APP` in `.env` (App Lab gives it to the teacher's container). Other apps and App Lab's examples are not checked: their icons are not stored pictures. Without `TEACHER_APP` it's printed as "not there";
- the folders holding `TEACHER_HEARTBEAT`, `TEACHER_MODE_FILE` and `TEACHER_CALIB` from `.env` (the folders mounted into the teacher's container);
- any folder listed in `PRIVACY_DIRS` in `.env` (separated by `:`), if another one is ever mounted;
- inside each running container (App Lab's), every file it added or changed, from Docker's API.

It skips installed library files (`site-packages`, `dist-packages`, `node_modules`), `.git` and `__pycache__`. A folder that isn't there is printed as "not there", never counted as checked.

Bytes out come from the counter in `board/privacy.nft`: every packet leaving the board, its containers included, to an address outside 192.168.77.0/24, 10.42.0.0/24, loopback, link-local, multicast and broadcast. The unit's one root step (`ExecStartPre=+`) loads that table; reading it needs CAP_NET_ADMIN, the only privilege the meter has. It needs the `nft` command (package `nftables`). If anything can't be read, `/privacy` says `"ok": false` and why, never a zero.

`sudo python3 -m board.privacy --explain` lists the bytes out by protocol and destination port (board/privacy-ports.nft, loaded on its own line so it can never stop the meter), with what each port usually is: udp 123 time sync, udp 53 name lookups, tcp 443 updates. These count since the table was loaded, so a reset doesn't clear them.

**The quiet step.** On the closed network the board's own background services still try to reach the internet: the time-sync client, apt's daily timers, firmware checks. Their packets go nowhere, but they leave the board, so the meter counts them. Every `deploy.sh` run on the board stops and disables the ones it finds (`QUIET_UNITS` in deploy.sh) and remembers them in `/var/lib/radio-sight/quieted-units`; the board's clock is set from the laptop instead (POST /clock). Before installing anything over a phone hotspot, run `sudo board/deploy.sh --install --online`: it starts exactly those services again. Deploy again without `--online` afterwards. Anything else that still sends shows in `--explain`, and the meter shows its bytes as they are. No firewall rule blocks anything; the only nftables rules are the meter's counters.

`board/egress.sh` is the proof run's own counter, a separate table: it doesn't touch this one.
