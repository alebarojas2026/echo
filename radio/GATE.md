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

**Pass criteria:** Pi beacon ≥ 20 adverts/s; each phone beacon ≥ 7 adverts/s.

**Setup:**
- Pi advertising as beacon S (manufacturer data `FFFF525353`).
- East and west phones advertising in nRF Connect as beacons E and W
  (`FFFF525345`, `FFFF525357`).
- `sudo python -m radio.hci_scan --node unoq` running on the board.
- Confirmed in btmon: `Filter duplicates: Disabled`.

| Beacon | Node ID | Adverts/s | Result |
|--------|---------|-----------|--------|
| pi5    | S       | __        | __     |
| east   | E       | __        | __     |
| west   | W       | __        | __     |

**Overall Gate 2:** __
