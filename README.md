# Echo

**A witness that never watches. It knows when someone is in a space, keeps a record nobody can edit, and tells you what happened. No camera, no microphone, nothing sent to the internet.**

Some places need a record of who was there and when, and cannot have cameras: server rooms and network cabinets, evidence rooms, labs after hours, restrooms, hotel rooms. Echo does it with the Wi-Fi signal alone.

- **It senses a person by radio.** Two small computers sit a metre apart. A body between them weakens the Wi-Fi signal, and from that one line the board knows someone arrived, whether they are standing still or moving, whether they walked through or stayed, and when they left. Armed, it raises an alert; it notices when one of its own devices is unplugged.
- **It seals what it sensed.** Every record is chained to the one before it, so a changed record breaks every seal after it and the board can name the record.
- **Two more machines vouch for it.** Each Raspberry Pi signs the board's latest record every five seconds with its own key.
- **It tells you what happened.** Ask it, and a program on the board answers in plain words from the sealed record, showing its steps.

It does not know who a person is and it does not know where in a room they are. It senses one spot.

Everything runs on an Arduino UNO Q (Qualcomm Dragonwing): the sensing, the records, the checking and a small language model. No cloud, no internet.

Built at MadHacks 2026 for the Qualcomm / N+1 Institute track. In this demo our own boards stand in for an access point and the devices a building already has, and one desk stands in for a room. What is measured is in [PROOF.md](PROOF.md).

## How it works (short)
1. Pi A is a Wi-Fi hotspot. Pi B, a metre away, measures how strong that signal is 25 times a second and sends the readings to the board.
2. The board compares each second with the level of the empty space. A drop that holds is a person; how steady it is says still or moving; how long it lasts says walked through or stayed.
3. Every second, and every event, is written to a record on the board. Each record carries the hash of the one before it.
4. Every five seconds each Pi signs the record's latest hash with its own Ed25519 key, and the board checks and stores the signature.
5. The screen shows the space and the person as a figure, and answers "what happened?" from the record. A second screen, the engine room, shows the devices, the record and the signatures live.

How the parts connect: [docs/network.md](docs/network.md)

## Repo layout
| Folder | What | Owner |
|---|---|---|
| `contracts/`, `CONTRACTS.md` | Message formats every part agrees on | Ivan |
| `web/src/room/`, `web/index.html`, `web/src/main.ts`, `web/package.json` | 3D room, radio links, radio image, web shell | Ivan |
| `web/src/hud/`, `web/tests/`, `scripts/` | Screen panels, demo tests and demo check script | Ivan |
| `radio/`, `pi/` | Signal readers on the UNO Q, Pi router and beacon setup | Alexander |
| `advisor/` | Wi-Fi link advice (not used in the demo) | Alexander |
| `board/`, `mcu/`, `bus/` | Board startup, LED grid, web server (port 8080), message bus and session recorder | Alexander |
| `brain/` | The live decision from the Wi-Fi line | Izet |
| `teacher/` | Camera labels during setup (not used in the demo) | Izet |
| `proof/` | Accuracy and latency measurements | Izet |
| `narrator/` | On-board plain-language explanations | Ivan |
| `sim/` | Simulated data and replay for development | Alejandro |
| `docs/`, `web/src/game/` | Docs and the "Can you hide from Wi-Fi?" scoreboard | Alejandro |

## Results
Measured numbers, methods and honest limits live in [PROOF.md](PROOF.md).

## Credits
Radio tomographic imaging: J. Wilson and N. Patwari, "Radio Tomographic Imaging with Wireless Networks" (IEEE TMC, 2010). Libraries are listed in each folder's requirements.

## License
MIT
