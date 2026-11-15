# Radio gate results

Gate tests decide whether the radio numbers are good enough for the demo.
Alexander fills in the measured rows; the CI script (`python3 -m radio.report_wifi`
and `python3 -m radio.report_hci`) checks them.

---

## Gate 1 — Wi-Fi link test (#19)

**Pass criteria:** ≥ 20 samples/s; a person in the line drops signal ≥ 3 dB,
3 out of 3 runs.

**Setup:**
- Pi at south node (S-home), board at north node — both at 1.0 m height. Nobody else in the square.
- Pi's 5 GHz hotspot up (`sudo bash pi/ap.sh` on the Pi).
- Board joined to the hotspot, locked to the Pi's BSSID, power saving off: `sudo bash radio/wifi_join.sh`
  on the board, with `SENSING_SSID`, `SENSING_PSK` and `SENSING_BSSID` in the board's `.env` (the BSSID
  is the `addr` line of `/usr/sbin/iw dev <hotspot interface> info` on the Pi; the full path works in any shell). It must print `joined`.
- On the board, from the repo, no sudo: `python3 -m radio.wifi_rssi --gate`. It pings the Pi 50 times a
  second (beacons alone are too few frames), walks through the three runs (line clear, then
  someone standing in the middle of the line, 10 s each) and prints the rate, rows and result below,
  ready to paste. Then `python3 -m radio.report_wifi` must print `GATE 1 PASS`.
- Desk layout (#415) only: Pi B runs the same gate for its own link, `pi5>pi5b:wifi`. On Pi B, after
  `sudo bash pi/install.sh --node pi5b` (which writes `WIFI_LINK` into its `.env` and joins Pi A's
  hotspot): `python3 -m radio.wifi_rssi --gate`, with the person standing between Pi A and Pi B.
  Paste its block under the second heading. `radio.report_wifi` checks one table per Wi-Fi link in
  radio/nodes.json, so the second table counts only once nodes.json has Pi B.

### pi5>unoq:wifi (Pi A to the board)

**Measured sample rate:** __ samples/s

| Run | Baseline dBm | Blocked dBm | Drop dB | Result |
|-----|-------------|------------|---------|--------|
| 1   | __          | __         | __      | __     |
| 2   | __          | __         | __      | __     |
| 3   | __          | __         | __      | __     |

### pi5>pi5b:wifi (Pi A to Pi B, desk layout)

**Measured sample rate:** __ samples/s

| Run | Baseline dBm | Blocked dBm | Drop dB | Result |
|-----|-------------|------------|---------|--------|
| 1   | __          | __         | __      | __     |
| 2   | __          | __         | __      | __     |
| 3   | __          | __         | __      | __     |

**Overall Gate 1:** __

---

## Gate 2 — Bluetooth raw scan (#20)

**Pass criteria:** a Pi's beacon (S, and B in the desk layout) ≥ 20 adverts/s at every receiver
that hears it; each of the E and W beacons ≥ 7 adverts/s at every receiver.

**Setup:**
- Pi advertising as beacon S (manufacturer data `FFFF525353`): `radio-sight-radio-node` running on the Pi.
- The E and W beacons (ESP32-S3, #305) powered at the east and west spots, advertising
  `FFFF525345` and `FFFF525357` in the advertising data (legacy, non-connectable). Phones aren't
  used: an iPhone can't put manufacturer data in its adverts (#289).
- On the board, `sudo systemctl stop radio-sight-hci-scan` first (one scanner at a time), then
  `sudo python3 -m radio.hci_scan --node unoq --seconds 60`. Its summary gives the three `>unoq` rows.
  Start the service again afterwards.
- On the Pi, before the board runs: `sudo systemctl stop radio-sight-radio-node`, then
  `sudo python3 -m pi.radio_node --seconds 300`, which covers all three board runs. It advertises S and
  forwards as usual, and at the end its summary gives the two `>pi5` rows (use the `lowest 10s` column).
  Start the service again afterwards.
- Desk layout (#415) only: Pi B advertises beacon B (`FFFF525342`) and listens too. Its
  `radio-sight-radio-node` runs with `RADIO_NODE=pi5b`; for the rows, stop it and run
  `sudo python3 -m pi.radio_node --node pi5b --seconds 300` on Pi B at the same time as the other two.
  The board's summary then also has `pi5b>unoq:ble`, Pi A's has `pi5b>pi5:ble`, and Pi B's has the three
  `>pi5b` rows. The five Pi B rows below are judged only once radio/nodes.json has Pi B.
- Confirmed in btmon: `Filter duplicates: Disabled`.

| Link          | Beacon | Adverts/s | Result |
|---------------|--------|-----------|--------|
| pi5>unoq:ble  | S      | __        | __     |
| east>unoq:ble | E      | __        | __     |
| west>unoq:ble | W      | __        | __     |
| east>pi5:ble  | E      | __        | __     |
| west>pi5:ble  | W      | __        | __     |
| pi5b>unoq:ble | B      | __        | __     |
| pi5>pi5b:ble  | S      | __        | __     |
| east>pi5b:ble | E      | __        | __     |
| west>pi5b:ble | W      | __        | __     |
| pi5b>pi5:ble  | B      | __        | __     |

Add a row per run, or write only the lowest of the three runs: `python3 -m radio.report_hci`
judges each link by its lowest rate. Write the rate as a bare number (`8.4`).

**Overall Gate 2:** __
