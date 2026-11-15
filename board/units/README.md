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
| radio-sight-radio-node (Pi only) | `python -m pi.radio_node` | root | no: it advertises and scans without the Ethernet link, and forwards once it's up |

A unit whose program doesn't exist yet still installs and keeps restarting until it does; `journalctl -u <unit>` shows why. If an older `llm.service` from the narrator README is installed, deploy removes it, so two model servers don't fight over port 8091.

## The privacy meter
`radio-sight-privacy` measures, every second, the image or video files on the board and the bytes it has sent out; the screen reads it from `GET /privacy` (board/serve.py, contract issue #620). `python -m board.privacy` prints one line; `python -m board.privacy reset` counts bytes from zero again and writes the time to `/var/lib/radio-sight-privacy/resets.log` and the journal.

Folders it checks for images and video (by name, and by their first bytes):
- `data/` in this checkout: sessions, the store, layout saves;
- `~/ArduinoApps`: App Lab's apps, the camera teacher included;
- the folders holding `TEACHER_HEARTBEAT`, `TEACHER_MODE_FILE` and `TEACHER_CALIB` from `.env` (the folders mounted into the teacher's container);
- any folder listed in `PRIVACY_DIRS` in `.env` (separated by `:`);
- inside each running container (App Lab's), every file it added or changed, from Docker's API.

It skips installed library files (`site-packages`, `dist-packages`, `node_modules`), `.git` and `__pycache__`. A folder that isn't there is printed as "not there", never counted as checked.

Bytes out come from the counter in `board/privacy.nft`: every packet leaving the board, its containers included, to an address outside 192.168.77.0/24, 10.42.0.0/24, loopback, link-local, multicast and broadcast. The unit's one root step (`ExecStartPre=+`) loads that table; reading it needs CAP_NET_ADMIN, the only privilege the meter has. It needs the `nft` command (package `nftables`). If anything can't be read, `/privacy` says `"ok": false` and why, never a zero.

`board/egress.sh` is the proof run's own counter, a separate table: it doesn't touch this one.
