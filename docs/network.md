# How Radio Sight Connects

Radio Sight keeps its application traffic inside the room. The board runs the message bus, sensing model, web app, and narrator. Pi A provides the sensing Wi-Fi, forwards both Pis' radio readings to the board, and routes a laptop browser to the board. Pi B is a second radio listener. Neither Pi runs a model.

## Two local paths

The board, two Pis, and demo laptop use two local network paths:

- A direct Ethernet cable connects Pi A at `192.168.77.1` to the board at `192.168.77.2`. It carries Pi A's readings, the readings Pi A forwards from Pi B, and the board's page data.
- A 5 GHz Wi-Fi hotspot on Pi A carries the sensing links, Pi B's readings, and light browser traffic. The hotspot is at `10.42.0.1`; the board and Pi B receive sensing addresses by DHCP, and the demo laptop joins it to open the live page. Pi B has no cable and no address is written into the repository.

The one Ethernet cable carries the Pi's radio messages and the board's page data even when the sensing link is deliberately obstructed. Do not copy files or bundles over the hotspot during a demo or recording; heavy traffic can starve the sensing link.

## Data flow

1. Radio readers on the board send measurements to the local message bus over UDP port `5600`.
2. Pi A sends its radio measurements across the Ethernet cable to UDP port `5600` on the board.
3. Pi B sends its readings to `192.168.77.2:5600` over Pi A's hotspot. Pi A forwards that traffic onto the Ethernet cable; Pi B has no Ethernet connection.
4. During setup, the camera teacher sends labels to the same bus through the local App Lab router on port `5600`.
5. The bus timestamps incoming messages and forwards them locally to the sensing model over UDP port `5601`.
6. The sensing model publishes live contract v2 state to the laptop browser through a WebSocket at `ws://192.168.77.2:8765/ws`.
7. The laptop joins Pi A's hotspot and opens `http://192.168.77.2:8080/?src=ws`. Pi A routes HTTP port `8080` and WebSocket port `8765` over the Ethernet cable to the board. The same local web service provides `/nodes.json` and `/proof.json`.
8. The narrator reaches its on-board language model through `http://127.0.0.1:8091`. That service is not exposed to the room network.

## Sensing links

The desk layout has twelve core classifier links: two Wi-Fi and ten Bluetooth. The UNO Q, Pi A, and Pi B are the three listeners; Pi A, Pi B, and the east and west ESP32-S3 boards advertise. Link ids, order, and positions come from `radio/nodes.json`, not this guide. Pi B's received links may make health `degraded` if its hotspot path loses packets, but they never make the whole sensor blind.

## Link bring-up

1. On Pi A, run `sudo bash pi/eth.sh` to configure its end of the direct cable.
2. On the UNO Q, run `sudo bash board/eth.sh` to configure the board end and confirm the Pi is reachable.
3. On Pi A, run `sudo bash pi/ap.sh` to start the private sensing hotspot.
4. On the UNO Q, run `sudo bash radio/wifi_join.sh` to join that hotspot with power saving disabled.
5. Join Pi B to the hotspot. Start `python -m pi.radio_node --node pi5b` and `WIFI_LINK=pi5>pi5b:wifi python -m radio.wifi_rssi` with `BUS_HOST=192.168.77.2` for both processes.
6. Join the demo laptop to the hotspot and open the live page. Keep hotspot use to Pi B's readings and the browser while a demo or recording is running.

The scripts read local hotspot values and any interface override from the ignored `.env` file. Never put those values in a public command, issue, or document.

## Service map

| Service | Runs on | Local endpoint | Role |
|---|---|---|---|
| Message bus | Board | UDP `5600` | Receives radio readings, setup labels, and commands |
| Model input | Board | UDP `127.0.0.1:5601` | Carries timestamped bus messages to the sensing model |
| Live state | Board | WebSocket `192.168.77.2:8765/ws` | Sends contract v2 state to the screen |
| Web interface | Board | HTTP `192.168.77.2:8080` | Serves the display, node layout, and proof results |
| Narrator model | Board | HTTP `127.0.0.1:8091` | Generates short local explanations |
| Pi B readers | Pi B | UDP to `192.168.77.2:5600` through Pi A | Adds the second listener's Wi-Fi and Bluetooth readings |
| Demo screen | Laptop | Browser on Pi A's hotspot | Displays the board's local web interface |

## What leaves the system

The live pipeline does not need a cloud connection. Radio readings, temporary setup labels, predictions, proof data, and narration stay on the board, the Pi, the demo laptop, or their local links.

The camera is only a setup teacher. It sends labels, not saved images. After setup, it can be unplugged while radio sensing and the screen continue to run.
