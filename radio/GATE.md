# Radio gate results

Gate tests decide whether the radio numbers are good enough for the demo.
Alexander fills in the measured rows; the CI script (`python -m radio.report_wifi`
and `python -m radio.report_hci`) checks them.

---

## Gate 1 — Wi-Fi link test (#19)

**Pass criteria:** ≥ 20 samples/s; a person in the line drops signal ≥ 3 dB,
3 out of 3 runs.

**Setup:**
- Pi at south node (S-home), board at north node — both at 1.0 m height.
- Pi's 5 GHz hotspot up (`sudo bash pi/ap.sh`).
- Board joined to sensing hotspot, power saving off (`sudo bash radio/wifi_join.sh`).
- `python -m radio.wifi_rssi` running on the board.

**Measured sample rate:** __ samples/s

| Run | Baseline dBm | Blocked dBm | Drop dB | Result |
|-----|-------------|------------|---------|--------|
| 1   | __          | __         | __      | __     |
| 2   | __          | __         | __      | __     |
| 3   | __          | __         | __      | __     |

**Overall Gate 1:** __

---

## Gate 2 — Bluetooth raw scan (#20)

**Pass criteria:** the Pi beacon ≥ 20 adverts/s at the board; each phone beacon ≥ 7 adverts/s
at the board and at the Pi.

**Setup:**
- Pi advertising as beacon S (manufacturer data `FFFF525353`): `radio-sight-radio-node` running on the Pi.
- East and west phones advertising in nRF Connect as beacons E and W
  (`FFFF525345`, `FFFF525357`). They must be Android phones: an iPhone can't put manufacturer
  data in its adverts (#289).
- On the board, `sudo systemctl stop radio-sight-hci-scan` first (one scanner at a time), then
  `sudo python -m radio.hci_scan --node unoq --seconds 60`. Its summary gives the three `>unoq` rows.
  Start the service again afterwards.
- On the Pi, before the board runs: `sudo systemctl stop radio-sight-radio-node`, then
  `sudo python3 -m pi.radio_node --seconds 300`, which covers all three board runs. It advertises S and
  forwards as usual, and at the end its summary gives the two `>pi5` rows (use the `lowest 10s` column).
  Start the service again afterwards.
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
