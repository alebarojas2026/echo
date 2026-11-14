# beacon

Firmware that turns a Seeed XIAO ESP32-S3 into one of our Bluetooth beacons. Two boards replace the east and west phones: an iPhone can't send the manufacturer data the scanners match (#289), and phones top out at about 10 adverts a second.

The current beacons are **E** (east) and **W** (west). The letter is chosen when you build, never from the board's address.

## What it sends

Legacy, non-connectable, undirected advertising (ADV_NONCONN_IND) on channels 37, 38 and 39, with no scan response (both scanners scan passively). The advertising data is 10 bytes, the same as the scanners' test fixture (radio/tests/fixtures/hci/legacy_report_east.hex):

| Bytes | Meaning |
|---|---|
| `02 01 06` | Flags: LE General Discoverable, no BR/EDR |
| `06 FF FF FF 52 53 45` | Manufacturer Specific Data: company 0xFFFF, then `R` `S` `E` (east) |
| `06 FF FF FF 52 53 57` | the same for `W` (west) |

radio/hci.py keeps a report only when the Manufacturer Specific Data is exactly `FFFF 52 53 <letter>`, and radio/nodes.json maps that to the beacon.

- **Interval: 35 ms**, fixed (min = max = 56 x 0.625 ms). The controller adds the spec's random 0-10 ms advDelay to every event by itself (Core spec Vol 6 Part B 4.4.2.2.1), so the sketch doesn't add its own, and events come every 40 ms on average: 25 a second, each sent on all three channels.
- **TX power: +9 dBm**, fixed, set explicitly for advertising when it starts and checked right after. It never changes while running, so a link's dBm only moves when something is in the way.
- The advert goes out from a random static address made fresh at each boot. Nothing reads, prints or sends the board's own address.

### Why 35 ms
Gate 2 (radio/GATE.md) needs at least 10 readings a second per link at each receiver. A passive scanner hears at most one of the three copies of each event, and it loses some: it hops channel every 10 ms, and the Pi and the board share their radio with Wi-Fi. At 25 events a second a link can lose more than half of them and still clear 10 a second.

On paper the three beacons together (S at about 20 ms, E and W at 35 ms) add up to about 90 adverts a second at each receiver: a few kilobytes a second of HCI events, and each 10-byte advert is on air for about 0.2 ms, so all three together fill about 2% of each advertising channel. That leaves the controllers plenty of room for the rest of the venue's Bluetooth traffic. 30 ms would add only about 4 events a second per beacon. 50 ms would drop to about 18 a second, which leaves less than twice the Gate 2 minimum.

### Why +9 dBm
Each beacon is about 1.4 m from each receiver. Free-space loss over 1.4 m at 2.4 GHz is about 43 dB, so +9 dBm arrives at about -34 dBm before antenna and mounting losses. That is far below the -10 dBm every Bluetooth LE receiver has to handle, and far above the receivers' noise floor, so a person in the line or the venue's Wi-Fi never pushes a reading into the noise. A lower level gives up that margin in a hall full of 2.4 GHz traffic. A higher one adds nothing inside a 2 m square and carries further into the venue. +9 dBm is also an exact step of the ESP32-S3's power table (it moves in 3 dB steps).

### When something goes wrong
- It should be advertising well within a second of a reset: setup sends five HCI commands (reset, random address, parameters, data, enable) and nothing else. To check, press **R** and watch for the first blink, which comes the moment advertising starts.
- A watchdog restarts the chip if the Bluetooth controller stops answering for 5 seconds. The sketch asks the controller for a reply every second and feeds the watchdog only when one comes back. A crash restarts it too.
- If any setup step fails, it says which one on USB serial and restarts.

### The lights
- **Orange LED:** one short blink every 3 seconds means it is advertising and the controller is answering. The first blink comes the moment advertising starts. Dark means it isn't advertising: it restarts itself within 5 seconds.
- **Red light by the USB port:** that's the battery charger, not this firmware. With no battery it comes on for about 30 seconds after you plug in, then goes off. Ignore it.

## Flash the boards (on the Mac)

Plug in **one board at a time**, and clip the antenna that came in its bag onto the board's antenna connector first.

### 1. arduino-cli (skip if `arduino-cli version` already prints 1.6.0 or newer)
```sh
mkdir -p ~/bin && cd ~/bin
ARCH=$([ "$(uname -m)" = arm64 ] && echo ARM64 || echo 64bit)
curl -fsSLO "https://downloads.arduino.cc/arduino-cli/arduino-cli_1.6.0_macOS_${ARCH}.tar.gz"
curl -fsSLO "https://downloads.arduino.cc/arduino-cli/1.6.0-checksums.txt"
grep "macOS_${ARCH}.tar.gz" 1.6.0-checksums.txt | shasum -a 256 -c -
tar xzf "arduino-cli_1.6.0_macOS_${ARCH}.tar.gz" arduino-cli
export PATH="$HOME/bin:$PATH"
arduino-cli version
```
The `shasum` line has to print `OK`.

### 2. The esp32 core (once)
```sh
ESP32_INDEX=https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core update-index --additional-urls "$ESP32_INDEX"
arduino-cli core install esp32:esp32@3.3.12 --additional-urls "$ESP32_INDEX"
```

### 3. Find the board's port
```sh
ls /dev/cu.usbmodem*
PORT=$(ls /dev/cu.usbmodem* | head -n 1); echo "$PORT"
```
With only the XIAO plugged in there is one `/dev/cu.usbmodem...` port. If there are more, unplug the XIAO, run `ls /dev/cu.usbmodem*` again, and the one that disappeared is the XIAO. Don't paste the port name anywhere.

### 4. Build and flash
From the repo folder (`cd` into your deadzone clone first).

East:
```sh
arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3 \
  --build-property "compiler.cpp.extra_flags=-DBEACON_ID='E'" \
  --build-path /tmp/beacon-E --upload --port "$PORT" beacon
```
Put a piece of tape marked **E** on the board itself (not on the floor), unplug it, plug in the second board, find its port again (step 3), then west:
```sh
arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3 \
  --build-property "compiler.cpp.extra_flags=-DBEACON_ID='W'" \
  --build-path /tmp/beacon-W --upload --port "$PORT" beacon
```
Tape it **W**. The first build takes a minute or two; later ones are quick.

Without `-DBEACON_ID=...` the build stops with an error on purpose, so a board can't be flashed with no letter.

### If the upload fails
Put the board in bootloader mode: unplug it, hold the **B** (BOOT) button, plug it in while holding, and let go after a second. Run step 3 again (the port can change), then the same compile command. When it finishes, press **R** (RESET) once, or unplug it and plug it back in.

### Check it over USB
```sh
arduino-cli monitor --port "$PORT" --config baudrate=115200
```
Every 10 seconds it prints a line like `beacon E: advertising FFFF 52 53 45 every 35.000 ms at +9 dBm (controller reports ...)`, with how long it has been up, and says so if the last restart came from the watchdog. Ctrl-C quits.

## Check it without our scanners

**A phone:** install nRF Connect (Android or iPhone; an iPhone can scan for these fine, it just can't send them). Open the scanner with no filters, hold the phone next to the beacon and find the strongest device with no name. Its manufacturer data should be company 0xFFFF with data `52 53 45` (E) or `52 53 57` (W); some versions show it as one string, `FFFF525345` or `FFFF525357`. It should not be connectable. On Android, nRF Connect also shows the interval it measures, which should sit around 40 ms and wander by a few ms (that's the random delay).

**btmon on the Pi or the board:**
```sh
sudo timeout 10 btmon | grep -A1 "(65535)"
```
Each of our adverts shows up as a `Company: ... (65535)` line followed by `Data: 525345` (E) or `Data: 525357` (W). This greps out only those two lines, so the addresses btmon prints never end up on screen. btmon only listens: it shows adverts when something is scanning. If `radio.hci_scan` is already running there, that's enough, and counting the lines gives the rate:
```sh
sudo timeout 10 btmon | grep -c "Data: 525345"    # E adverts in 10 s; divide by 10 for adverts/s
```
If nothing is scanning, start a scan in a second terminal with `sudo bluetoothctl --timeout 15 scan on`. That scan filters duplicates, so it only shows that the beacon is there, not how fast it sends. The Gate 2 numbers come from the run in radio/GATE.md.

## Where they go
- E at the midpoint of the square's east side, W at the midpoint of the west side (radio/nodes.json: (2.0, 1.0) and (0.0, 1.0)).
- Both at 1.0 m, antenna end up, both boards held the same way round.
- Labels on the boards themselves, not on the floor.

## Power
Any USB-C phone charger or power bank works. The board draws very little current, and some power banks decide nothing is plugged in and switch off after a while. A wall charger avoids that. With a power bank, switch on its low-current (trickle) mode if it has one (often a long or double press of its button; check its manual), then leave the beacon on it for a couple of minutes and check the orange LED is still blinking.

## Other letters
`BEACON_ID` can be any single uppercase letter except `S` (the Pi's beacon), for example `-DBEACON_ID='N'` for an extra corner beacon. The scanners only keep letters listed in radio/nodes.json, so a new letter needs its payload (and its links) added there before it shows up anywhere.

## CI
`.github/workflows/beacon.yml` builds E and W on every pull request that touches `beacon/` or the scanners' beacon code, with the core cached between runs. After each build, `beacon/check_advert.py` finds the advertising data in the binary and runs it through radio/hci.py's parser and radio/nodes.json, so the firmware and the scanners can't drift apart. To run the same check on a local build:
```sh
python3 beacon/check_advert.py /tmp/beacon-E/beacon.ino.bin E
```
