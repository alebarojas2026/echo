# Units

systemd units for every program in CONTRACTS.md section 9. Install them with `board/deploy.sh`, never by copying by hand, because the files here have placeholders.

## Install on the board
From the repo root, with the Python env already at /opt/rs/venv:
```sh
sudo board/deploy.sh --install --no-pi   # before the Pi is connected
sudo board/deploy.sh --install           # once the Pi's hotspot and the Ethernet link are up (pi/eth.sh on the Pi, board/eth.sh here)
```
Each run installs every unit, reloads systemd, enables them, and starts any that aren't running. It restarts only units whose file changed. Running it again is safe.

`--no-pi` still installs the units that need the Pi (`radio-sight-wifi-rssi` and `radio-sight-hci-scan`, the BLE scan), but stops and disables them, so they don't crash-loop. Run it again without `--no-pi` to start them.

Check:
```sh
systemctl list-units 'radio-sight-*'
journalctl -u radio-sight-bus -f
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
| radio-sight-radio-node (Pi only) | `python -m pi.radio_node` | root | no: it advertises and scans without the Ethernet link, and forwards once it's up |

A unit whose program doesn't exist yet still installs and keeps restarting until it does; `journalctl -u <unit>` shows why. If an older `llm.service` from the narrator README is installed, deploy removes it, so two model servers don't fight over port 8091.
