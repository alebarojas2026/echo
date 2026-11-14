# Build Radio Sight

Radio Sight uses radio links around one room to map signal change, locate real dead zones, and classify presence, movement, and objects. All learned work runs locally on the Arduino UNO Q's Dragonwing CPU; the Raspberry Pi provides the sensing network and screen and runs no model.

## Parts

- Arduino UNO Q
- Raspberry Pi 5 with its power supply
- powered USB-C hub with Ethernet and power delivery for the UNO Q
- Ethernet cable between the Pi and the UNO Q's hub
- USB webcam for setup labels only
- two ESP32-S3 boards configured as the east and west Bluetooth beacons
- display, keyboard, and pointing device for setup
- stands that hold every radio node at the same height
- loose floor markers for building and testing
- tape for the final presentation-hour layout

The demo uses its own equipment and private network. Do not plan around venue Wi-Fi.

## What each part does

- **UNO Q:** receives radio readings and runs the bus, signal health, model training and inference, radio X-ray, check-in logic, no-movement alert logic, advisor, narration, and web service.
- **Pi:** creates the private sensing hotspot, acts as a radio node, and drives the display. It runs no model.
- **ESP32-S3 beacons:** advertise the east and west beacon patterns. The software matches advertised data, not device identity; phones are not used as beacons.
- **Webcam:** supplies temporary person, zone, and motion labels for calibration and training. Disconnect it for the live radio-only demonstration; no image or video is saved.

## Connect the hardware

1. Power the UNO Q through the powered hub and connect the webcam and hub Ethernet.
2. Connect the hub Ethernet directly to the Pi's Ethernet port. This cable carries the bus, model state, web page, and setup traffic.
3. Connect the Pi to the demo display.
4. Put the UNO Q at the north marker, the Pi at the south marker, and the ESP32-S3 beacons at the east and west markers. The contract layout is a square with every node at `1.0 m` high.
5. Keep cables outside the walking area and keep the router at its home mark before calibration.

For the exact network roles and contract addresses, follow the [network guide](network.md). Use only the addresses already defined by `CONTRACTS.md`; keep local network credentials out of the repository.

## Setup order

### Finish internet installs first

Install system packages, Python dependencies, the Arduino App Bricks wheel, and web dependencies while the board still has internet access. Build the web app and download any local model files before joining the isolated sensing hotspot, because the board has no internet there.

### Mark the layout with loose markers

During the build, measure the square and mark the four node positions with removable, loose markers. Set all radio nodes at `1.0 m`, leave the walking area clear, and do not tape the floor yet.

### Calibrate the setup camera

Mount the webcam where it sees the whole marked square without moving. Calibrate its floor coordinates against the same loose markers, confirm the teacher reports the expected zone and motion, and confirm that it writes no image or video file.

### Start the Pi's private hotspot

Start the Pi's sensing hotspot, then join the UNO Q to it and keep Wi-Fi power saving off. The hotspot carries sensing traffic only; all other traffic stays on the direct Ethernet cable described in the [network guide](network.md).

### Run the signal test

Start the Pi radio node and the UNO Q radio readers. Confirm every required Wi-Fi and Bluetooth link is updating, the screen shows fresh `live` state, and health is `ok`; fix a missing link before baseline or training.

### Baseline and train

Clear people and movable objects from the square, turn label mode off, and capture the `20 s` baseline. Then enable setup labels, record representative person and object sessions, train on the UNO Q, and verify held-out proof values before treating a result as measured.

### Prove radio-only operation

After successful training, unplug the webcam in view of the display. Confirm camera status is off, the teacher field is absent, radio state remains live, and every unmeasured public result still renders as `__`.

## Presentation-room reset

Do not assume the build-room calibration survives a move. In the presentation room:

1. Measure the layout again and tape the final floor marks only now.
2. Place every node on its assigned mark at `1.0 m` and return the router to its home position.
3. Redo the camera calibration against the taped square.
4. Redo the `20 s` baseline and training in that room.
5. Repeat the signal-health check, camera-unplug proof, and measured demo path.

If a required link is blind, the correct result is no prediction, not "empty." Fix the radio path and repeat the affected setup step rather than presenting a guessed value.
