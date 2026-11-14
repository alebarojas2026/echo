# Radio gate results

Gate tests decide whether the radio numbers are good enough for the demo.
Alexander fills in the measured rows; the CI script (`python -m radio.report_wifi`
and `python -m radio.report_hci`) checks them.

---

## Gate 1 — Wi-Fi link test (#19)

**Pass criteria:** ≥ 20 samples/s; a person in the line drops signal ≥ 3 dB,
3 out of 3 runs.

**Setup:**
- Pi at south node (S-home), board at north node — both at 1.0 m height. Nobody else in the square.
- Pi's 5 GHz hotspot up (`sudo bash pi/ap.sh` on the Pi).
- Board joined to the hotspot, locked to the Pi's BSSID, power saving off: `sudo bash radio/wifi_join.sh`
  on the board, with `SENSING_SSID`, `SENSING_PSK` and `SENSING_BSSID` in the board's `.env` (the BSSID
  is the `addr` line of `iw dev <hotspot interface> info` on the Pi). It must print `joined`.
- On the board, from the repo, no sudo: `python -m radio.wifi_rssi --gate`. It pings the Pi 50 times a
  second (beacons alone are too few frames), walks through the three runs (line clear, then
  someone standing in the middle of the line, 10 s each) and prints the rate, rows and result below,
  ready to paste. Then `python -m radio.report_wifi` must print `GATE 1 PASS`.

**Measured sample rate:** __ samples/s

| Run | Baseline dBm | Blocked dBm | Drop dB | Result |
|-----|-------------|------------|---------|--------|
| 1   | __          | __         | __      | __     |
| 2   | __          | __         | __      | __     |
| 3   | __          | __         | __      | __     |

**Overall Gate 1:** __

---

## Gate 2 — Bluetooth raw scan (#20)

**Pass criteria:** the Pi beacon ≥ 20 adverts/s at the board; each of the E and W beacons ≥ 7
adverts/s at the board and at the Pi.

**Setup:**
- Pi advertising as beacon S (manufacturer data `FFFF525353`): `radio-sight-radio-node` running on the Pi.
- The E and W beacons (ESP32-S3, #305) powered at the east and west spots, advertising
  `FFFF525345` and `FFFF525357` in the advertising data (legacy, non-connectable). Phones aren't
  used: an iPhone can't put manufacturer data in its adverts (#289).
- On the board, `sudo systemctl stop radio-sight-hci-scan` first (one scanner at a time), then
  `sudo python -m radio.hci_scan --node unoq --seconds 60`. Its summary gives the three `>unoq` rows.
  Start the service again afterwards.
- On the Pi, the radio node's status line (`journalctl -u radio-sight-radio-node -f`, every 10 s)
  gives the two `>pi5` rows. Use the lowest value over 60 s.
- Confirmed in btmon: `Filter duplicates: Disabled`.

| Link          | Beacon | Adverts/s | Result |
|---------------|--------|-----------|--------|
| pi5>unoq:ble  | S      | __        | __     |
| east>unoq:ble | E      | __        | __     |
| west>unoq:ble | W      | __        | __     |
| east>pi5:ble  | E      | __        | __     |
| west>pi5:ble  | W      | __        | __     |

Add a row per run, or write only the lowest of the three runs: `python -m radio.report_hci`
judges each link by its lowest rate. Write the rate as a bare number (`8.4`).

**Overall Gate 2:** __
