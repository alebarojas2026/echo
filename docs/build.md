# Build Echo

Echo senses one spot with one Wi-Fi line, keeps a sealed record of what it sensed, and answers "What happened?" from that record. Everything runs locally on the Arduino UNO Q's Dragonwing CPU. Pi A makes the Wi-Fi signal and Pi B measures it; neither Pi runs a model. A laptop browser shows the local interface.

## Parts

- Arduino UNO Q
- two Raspberry Pi 5 boards with their power supplies: Pi A, the hotspot, and Pi B, the far end of the line
- powered USB-C hub with Ethernet and power delivery for the UNO Q
- Ethernet cable between Pi A and the UNO Q's hub
- laptop for the demo browser and setup controls; a second laptop for the engine room; a phone for the alarm page
- something to hold Pi B at desk height across the gap
- loose markers for building and testing
- tape for the final presentation-hour layout

There is no camera and no microphone on the kit. The demo uses its own equipment and private network. Do not plan around venue Wi-Fi.

## What each part does

- **UNO Q:** receives the readings and runs the bus, the decision, the alerts, the sealed record, the signature checks, the answers, the narration and the web server.
- **Pi A:** creates the private 5 GHz hotspot whose signal is the sensor, routes the screens and Pi B's readings to the board over the direct Ethernet cable, and signs the record. It runs no model.
- **Pi B:** measures Pi A's signal across the gap continuously and signs the record. It has no cable, joins Pi A's hotspot, and sends its readings to the board through Pi A. It runs no model.
- **Laptops and phone:** join the Pi hotspot and display the board's pages. Keep hotspot traffic to the live pages; do not copy files or bundles over the hotspot during a demo or recording.

## Connect the hardware

1. Power the UNO Q through the powered hub and connect the hub's Ethernet.
2. Connect the hub Ethernet directly to Pi A's Ethernet port. This one cable carries Pi B's forwarded readings, both Pis' signatures, the state, the pages and setup traffic.
3. Put the UNO Q and Pi A side by side on one desk.
4. Put Pi B across a gap of 85 to 100 cm, at desk height. On a chair seat it fails: keep it at desk height.
5. Keep cables and bags out of the gap, and secure Pi B's power cable.

For the exact network roles and contract addresses, follow the [network guide](network.md). Use only the addresses already defined by `CONTRACTS.md`; keep local network credentials out of the repository.

## Setup order

### Finish internet installs first

Install system packages, Python dependencies and web dependencies while the board still has internet access. Download the local model file before joining the isolated hotspot, because the board has no internet there. Do not build the web page yet: the layout is chosen first.

### Choose the layout, then build the page

First switch the layout: run `python3 -m radio.use_layout gate` on all three devices and in the laptop's copy of the repository. Only then build the web page; it goes onto the board with `board/push-web.sh` once the cable link is up, never while a demo or a recording is running. The order matters because the page carries the layout it was built with.

### Bring up the direct Ethernet link

With the one Ethernet cable connected, run `sudo bash pi/eth.sh` on Pi A and `sudo bash board/eth.sh` on the UNO Q. The scripts create the contract-defined addresses and confirm that the two ends can reach each other. Keep any local interface choice in the ignored `.env` file.

### Start Pi A's private hotspot

Run `sudo bash pi/ap.sh` on Pi A, then run `sudo bash radio/wifi_join.sh` on the UNO Q. Join Pi B to the same hotspot and start its readers with `BUS_HOST=192.168.77.2`; its address comes from DHCP and is never written into the repository. Never run `pi/install.sh --wifi-off` on Pi B: that takes the only sensor down.

### Set up the signing on each Pi

On each Pi, once, run `python3 -m pi.witness --init`. The key is made on the Pi and never leaves it. The command prints the public key; only the public key goes in the board's local key file, `data/witness_keys.local.json`, which git ignores. Never paste a key into an issue, a chat or a document. Then restart the services and check the signing program is running on each Pi.

### Set the clocks

Set the board's clock from the laptop after every power-up. Pi B's clock resets whenever it loses power, so set it too before the baseline.

### Run the signal test

On the board run `python3 -m radio.check`, on Pi A `python3 -m pi.check`, and on Pi B `python3 -m pi.check --node pi5b`. Every line is ok, and `pi5>pi5b:wifi` is listed and updating. Fix a missing line before the baseline.

### Take the baseline

Clear people and movable things from the gap, with nobody within 2 m, and capture the `20 s` baseline. The headline then says "Nobody is here". There is no training: after the baseline the line alone gives the decision. Take the baseline again after every deploy, every power-up and any device being moved.

### Open the pages

Join each screen to the hotspot and open its page: the judge's page `http://192.168.77.2:8080/`, the engine room `http://192.168.77.2:8080/engine/`, and the alarm page `http://192.168.77.2:8080/phone/`. Then check the sealed record: `http://192.168.77.2:8080/chain` shows the record counting up, verified, with both Pis signing.

## Presentation-room reset

Do not assume the build-room setup survives a move. In the presentation room:

1. Place the three devices again, measure the gap, and tape their places only now.
2. Set the board's clock, and set Pi B's clock: it resets whenever Pi B loses power. Then check the signal test.
3. Place the screen: press `P` on the judge's page, click the desk the board is on, and press `Enter`.
4. Redo the `20 s` baseline with the gap empty.
5. Stand on the spot once and check the figure appears, then check both Pis are signing on the engine room.

A bag that blocks the line as much as a body reads as a person standing still.

If the Wi-Fi line is not reporting, the correct result is no decision, not "empty." Fix the line and repeat the baseline; never present a guessed value.
