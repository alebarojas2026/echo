# Radio Sight

**Wi-Fi that understands the room.** Your Wi-Fi can't tell a wall from a person. Radio Sight can.

It reads how bodies and objects change the radio signals already in a room, builds a live radio picture of the space, finds real dead zones, and knows whether someone is present and moving, without a camera and without the cloud. Everything runs on an Arduino UNO Q (Qualcomm Dragonwing).

Built at MadHacks 2026 for the Qualcomm / N+1 Institute track. Theme: "Let's Dig In."

## How it works (short)
1. Small radio nodes around a floor zone (the UNO Q, a Raspberry Pi 5 acting as the router, and beacons) measure signal strength on every link many times a second.
2. During setup, a camera on the UNO Q labels where a person is. A small model on the board learns to predict the same thing from radio alone. Then the camera is unplugged.
3. The board combines all links into a radio image of the room: what stays put is an obstruction or dead zone, what moves is a person.
4. The screen shows the room, the radio links, where people are, and plain-language explanations. No image is ever saved and nothing leaves the board.

How the parts connect: [docs/network.md](docs/network.md)

## Repo layout
| Folder | What | Owner |
|---|---|---|
| `contracts/`, `CONTRACTS.md` | Message formats every part agrees on | Ivan |
| `web/src/room/`, `web/index.html`, `web/src/main.ts`, `web/package.json` | 3D room, radio links, radio image, web shell | Ivan |
| `web/src/hud/`, `web/tests/`, `scripts/` | Screen panels, demo tests and demo check script | Ivan |
| `radio/`, `pi/` | Signal readers on the UNO Q, Pi router and beacon setup | Alexander |
| `advisor/` | Dead-zone placement advice | Alexander |
| `board/`, `mcu/`, `bus/` | Board startup, LED grid, web server (port 8080), message bus and session recorder | Alexander |
| `brain/` | Features, on-board training, live predictions | Izet |
| `teacher/` | Camera labels during setup (no images saved) | Izet |
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
