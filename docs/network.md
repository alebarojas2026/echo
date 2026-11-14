# How Radio Sight Connects

Radio Sight keeps its application traffic inside the room. The board runs the message bus, sensing model, web app, and narrator. The Pi provides the sensing Wi-Fi, forwards its radio readings to the board, and runs the browser shown on the demo screen.

## Two local paths

The board and Pi use two separate network paths:

- A direct Ethernet cable carries application traffic between them. The Pi uses `192.168.77.1` and the board uses `192.168.77.2` on this link.
- A 5 GHz Wi-Fi hotspot on the Pi is used for sensing. The hotspot is at `10.42.0.1`; the board receives its sensing address from the hotspot.

Keeping sensing Wi-Fi separate from the Ethernet link gives radio collection a clear job while the cable carries messages, the web interface, and proof data.

## Data flow

1. Radio readers on the board send measurements to the local message bus over UDP port `5600`.
2. The Pi sends its radio measurements across the Ethernet cable to UDP port `5600` on the board.
3. During setup, the camera teacher sends labels to the same bus through the local App Lab router on port `5600`.
4. The bus timestamps incoming messages and forwards them locally to the sensing model over UDP port `5601`.
5. The sensing model publishes live contract v2 state to the screen through a WebSocket at `ws://192.168.77.2:8765/ws`.
6. The screen loads the web interface from `http://192.168.77.2:8080`. The same local web service provides `/nodes.json` and `/proof.json`.
7. The narrator reaches its on-board language model through `http://127.0.0.1:8091`. That service is not exposed to the room network.

## Service map

| Service | Runs on | Local endpoint | Role |
|---|---|---|---|
| Message bus | Board | UDP `5600` | Receives radio readings, setup labels, and commands |
| Model input | Board | UDP `127.0.0.1:5601` | Carries timestamped bus messages to the sensing model |
| Live state | Board | WebSocket `192.168.77.2:8765/ws` | Sends contract v2 state to the screen |
| Web interface | Board | HTTP `192.168.77.2:8080` | Serves the display, node layout, and proof results |
| Narrator model | Board | HTTP `127.0.0.1:8091` | Generates short local explanations |
| Demo screen | Pi | Browser in kiosk mode | Displays the board's local web interface |

## What leaves the system

The live pipeline does not need a cloud connection. Radio readings, temporary setup labels, predictions, proof data, and narration stay on the board, the Pi, or the direct link between them.

The camera is only a setup teacher. It sends labels, not saved images. After setup, it can be unplugged while radio sensing and the screen continue to run.
