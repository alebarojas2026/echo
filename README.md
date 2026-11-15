# Radio Sight

**Safety and after-hours security for buildings, using the Wi-Fi that's already there. No cameras.**

Every building has Wi-Fi. Radio Sight reads how people and objects change those radio signals, and does three things with them:

- **Safety and security.** It knows someone is in a space, on which side, and whether they've been still too long. Armed, it raises an alert when a space that should be empty isn't, and it notices when one of its own devices is unplugged.
- **Privacy.** No camera watches anyone. A camera teaches the radio for about half a minute and is then unplugged. No image is ever stored, nothing is sent to the internet, and it can't tell who someone is. It works where cameras can't go: patient rooms, bathrooms, study rooms, offices after hours.
- **Dead zones.** The same links that sense people show where the Wi-Fi itself is weak or blocked. When something blocks a link it says so, says where to move the router, and measures the gain.

Everything runs on an Arduino UNO Q (Qualcomm Dragonwing): the sensing, the learning, the records and a small language model that answers questions about what happened. No cloud, no internet.

Built at MadHacks 2026 for the Qualcomm / N+1 Institute track. In this demo our own boards stand in for the access points a building already has, and one desk stands in for a room. What is measured is in [PROOF.md](PROOF.md); anything not measured there is not claimed.

## How it works (short)
1. Small radio nodes around a floor zone (the UNO Q, a Raspberry Pi 5 acting as the router, and beacons) measure signal strength on every link many times a second.
2. During setup, a camera on the UNO Q labels where a person is. A small model on the board learns to predict the same thing from radio alone. Then the camera is unplugged.
3. The board combines all links into a radio image of the room: what stays put is an obstruction or dead zone, what moves is a person.
4. The screen shows the room, the radio links, where people are, and plain-language explanations. No image is ever saved and nothing is sent to the internet.

## What this demo is and isn't
- A building already has access points and other radios. In this demo our own two Raspberry Pis and the UNO Q stand in for them, on our own hotspot. Running on a building's installed equipment is not tested.
- The camera is needed for the lesson, and a new place needs a new lesson. It is not needed afterwards.
- Every number we quote is measured and has a row in [PROOF.md](PROOF.md). A row with no value has not been measured yet.

How the parts connect: [docs/network.md](docs/network.md)

## Repo layout
| Folder | What | Owner |
|---|---|---|
| `contracts/`, `CONTRACTS.md` | Message formats every part agrees on | Ivan |
| `web/src/room/`, `web/index.html`, `web/src/main.ts`, `web/package.json` | 3D room, radio links, radio image, web shell | Ivan |
| `web/src/hud/`, `web/tests/`, `scripts/` | Screen panels, demo tests and demo check script | Ivan |
| `radio/`, `pi/` | Signal readers on the UNO Q, Pi router and beacon setup | Alexander |
| `advisor/` | Dead-zone placement advice | Izet |
| `board/`, `mcu/`, `bus/` | Board startup, LED grid, web server (port 8080), message bus and session recorder | Alexander |
| `brain/` | Features, on-board training, live predictions | Izet |
| `teacher/` | Camera labels during setup (no images saved) | Alejandro |
| `proof/` | Accuracy and latency measurements | Izet |
| `narrator/` | On-board plain-language explanations | Alejandro |
| `sim/` | Simulated data and replay for development | Alejandro |
| `docs/`, `web/src/game/` | Docs and the "Can you hide from Wi-Fi?" scoreboard | Alejandro |

## Results
Measured numbers, methods and honest limits live in [PROOF.md](PROOF.md).

## Credits
Radio tomographic imaging: J. Wilson and N. Patwari, "Radio Tomographic Imaging with Wireless Networks" (IEEE TMC, 2010). Libraries are listed in each folder's requirements.

## License
MIT
