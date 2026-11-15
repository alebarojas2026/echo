# Build Echo

Echo uses radio links around one room to map signal change, locate real dead zones, and classify presence, movement, and objects. All learned work runs locally on the Arduino UNO Q's Dragonwing CPU; Pi A provides the sensing network, and Pi B adds a second listener. Neither Pi runs a model. A laptop browser shows the local interface.

## Parts

- Arduino UNO Q
- two Raspberry Pi 5 boards with their power supplies: Pi A, the router, and Pi B, the second listener
- powered USB-C hub with Ethernet and power delivery for the UNO Q
- Ethernet cable between Pi A and the UNO Q's hub
- USB webcam for setup labels only
- two ESP32-S3 boards configured as the east and west Bluetooth beacons
- laptop for the demo browser and setup controls
- three `25 cm` boxes for the UNO Q, Pi A, and Pi B
- two cardboard arms for the east and west ESP32-S3 beacons
- a measuring string knotted at `0`, `0.5`, `0.8`, `1.1`, and `1.6 m`
- loose floor markers for building and testing
- tape for the final presentation-hour layout

The demo uses its own equipment and private network. Do not plan around venue Wi-Fi.

## What each part does

- **UNO Q:** receives radio readings and runs the bus, signal health, model training and inference, radio X-ray, check-in logic, no-movement alert logic, advisor, narration, and web service.
- **Pi A:** creates the private sensing hotspot, acts as the router and a radio node, and routes the laptop browser and Pi B's readings to the board over the direct Ethernet cable. It runs no model.
- **Pi B:** is a second radio listener. It has no cable, joins Pi A's hotspot, and sends readings to the board through Pi A. It runs no model.
- **Laptop:** joins the Pi hotspot and displays the board's local web interface. Keep its hotspot traffic to the live page; do not copy files or bundles during a demo or recording.
- **ESP32-S3 beacons:** advertise the east and west beacon patterns. The software matches advertised data, not device identity; phones are not used as beacons.
- **Webcam:** supplies temporary person, zone, and motion labels for calibration and training. Disconnect it for the live radio-only demonstration; no image or video is saved.

## Connect the hardware

1. Power the UNO Q through the powered hub and connect the webcam and hub Ethernet.
2. Connect the hub Ethernet directly to Pi A's Ethernet port. This cable carries Pi A's readings, Pi B's forwarded readings, model state, web page, and setup traffic.
3. Put the demo laptop near the display area. It needs no cable or switch; join it after the private hotspot starts.
4. Put the UNO Q, Pi A, and Pi B on their three `25 cm` boxes on the desk. Put the east and west ESP32-S3 beacons on the tips of the two cardboard arms over the aisle.
5. Set every antenna at `1.0 m`, keep cables out of the `1.6 x 0.6 m` sensing strip, and keep Pi A at `S-home` before calibration.

For the exact network roles and contract addresses, follow the [network guide](network.md). Use only the addresses already defined by `CONTRACTS.md`; keep local network credentials out of the repository.

## Setup order

### Finish internet installs first

Install system packages, Python dependencies, the Arduino App Bricks wheel, and web dependencies while the board still has internet access. Build the web app and download any local model files before joining the isolated sensing hotspot, because the board has no internet there.

### Bring up the direct Ethernet link

With the one Ethernet cable connected, run `sudo bash pi/eth.sh` on the Pi and `sudo bash board/eth.sh` on the UNO Q. The scripts create the contract-defined addresses and confirm that the two ends can reach each other. Keep any local interface choice in the ignored `.env` file.

### Mark the layout with loose markers

During the build, measure the `1.6 x 0.6 m` aisle strip and the desk edge with removable, loose markers. Use the measuring string knotted at `0`, `0.5`, `0.8`, `1.1`, and `1.6 m` to place the five nodes from `radio/nodes.json`: the strip ends, zone split, Pi B, UNO Q, and Pi A's home position. Leave the strip clear and do not tape the floor or cardboard arms yet.

### Calibrate the setup camera

Mount the webcam on the desk facing the person in the whole marked strip. Calibrate its Left/Right split against the same loose markers, confirm the teacher reports the expected zone and motion, and confirm that it writes no image or video file.

### Start Pi A's private hotspot

Run `sudo bash pi/ap.sh` on Pi A, then run `sudo bash radio/wifi_join.sh` on the UNO Q. Join Pi B to the same hotspot and start its two radio readers with `BUS_HOST=192.168.77.2`; its address comes from DHCP and is never written into the repository. The board join script locks the board to the sensing hotspot and disables Wi-Fi power saving. Join the demo laptop to the hotspot and open `http://192.168.77.2:8080/?src=ws`. The hotspot carries sensing, Pi B's readings, and light browser traffic; Pi A forwards Pi B and the browser over its direct Ethernet cable to the board. Do not copy files or bundles over the hotspot during a demo or recording.

### Run the signal test

Start both Pi radio nodes and the UNO Q radio readers. Confirm all twelve core links—two Wi-Fi and ten Bluetooth—are updating, the screen shows fresh `live` state, and health is `ok`; fix a missing link before baseline or training.

### Baseline and train

Clear people and movable objects from the sensing strip and desk, turn label mode off, and capture the `20 s` baseline. Then enable setup labels, record representative person and object sessions, train on the UNO Q, and verify held-out proof values before treating a result as measured.

If a cardboard arm or node is bumped after training, secure it, restore every position from `radio/nodes.json`, keep the strip empty, and start `baseline {keep_model: true}`. This `20 s` same-layout baseline may run with the camera unplugged and keeps the trained model. A plain `baseline {}` means a new place and drops the model.

### Prove radio-only operation

After successful training, unplug the webcam in view of the display. Confirm camera status is off, the teacher field is absent, radio state remains live, and every unmeasured public result still renders as `__`.

## Presentation-room reset

Do not assume the build-room calibration survives a move. In the presentation room:

1. Measure the strip again and tape the final floor marks and cardboard arms only now.
2. Place every node on its assigned mark at `1.0 m` and return Pi A to `S-home`.
3. Redo the camera calibration against the taped strip and Left/Right split.
4. Redo the `20 s` baseline and training in that room.
5. Repeat the signal-health check, camera-unplug proof, and measured demo path.

If a required link is blind, the correct result is no prediction, not "empty." Fix the radio path and repeat the affected setup step rather than presenting a guessed value.
