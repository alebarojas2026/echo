# sim

Fake radio data so everyone can test without hardware. Not used in the live demo.
Python standard library only (pytest for the tests).

Run everything from the repo root.

## Make fake data

```
python -m sim.fake my_path.json            # real time, JSON lines on stdout
python -m sim.fake my_path.json --fast     # all at once, for recording a file
```

Options: `--rate 15` (readings per link per second, 10-20), `--seed 0` (same seed, same data),
`--start-ms` (epoch ms of the first message; default is now).

## Run the whole system with no hardware

```
python -m bus                          # in one terminal (and brain, web server, ...)
python -m sim.send zone_tour --loop    # in another
```

`sim.send` sends the same feed as `sim.fake`, one message per UDP datagram, to the
bus at `127.0.0.1:5600`, at real speed and stamped with the real clock. Give it a
recorded `.jsonl` file instead of a path name and it replays that file (`"src":"replay"`).
Options: `--host`, `--port`, `--rate`, `--seed`, `--speed`, `--loop`.

## The room

Nodes, links and zones are the ones in CONTRACTS.md section 3.

```
y=2 +----unoq----+      zones:  1 Bed   | 2 Chair       0 = empty
    |  1  |  2   |              --------+-----------
  west----+----east             3 Hall  | 4 Bathroom
    |  3  |  4   |
y=0 +----pi5-----+
   x=0          x=2   (metres, x east, y north)
```

Six links: `pi5>unoq:wifi`, `pi5>unoq:ble`, `east>unoq:ble`, `west>unoq:ble`, `east>pi5:ble`, `west>pi5:ble`.
A person near the line between two nodes drops that link by up to 8 dB; every reading also has
about 1 dB of noise. Each diagonal link crosses exactly one zone.

## Output

One JSON object per line, in the CONTRACTS.md v2 format (sections 1 and 4), with `"src":"sim"`:

```
{"v":2,"type":"meta","t":1763149500000,"seq":1,"src":"sim","session":"sim-zone_tour","purpose":"demo","walker":"sim"}
{"v":2,"type":"rssi","t":1763149500000,"seq":2,"src":"sim","link":"pi5>unoq:wifi","kind":"wifi","tx":"pi5","rx":"unoq","dbm":-45}
{"v":2,"type":"label","t":1763149500000,"seq":8,"src":"sim","frame":0,"mode":"person","persons_in_frame":1,"present":true,"zone":3,"foot_m":[0.0,0.5],"motion":"moving","conf":0.81,"clipped":false}
{"v":2,"type":"cam","t":1763149500000,"seq":9,"src":"sim","state":"on","fps":7.5}
```

- `meta` once at the start, `rssi` for every link on every tick, `label` 7.5 times a second
  (empty frames too), `cam` once a second.
- The whole feed is one producer: `seq` goes up by one per line.
- With nobody in the room a label has `present:false`, `zone:0`, `foot_m:null`, `motion:null`.
- `motion` follows the contract rule: moving means faster than 0.25 m/s over the last second.

The format lives in `sim/wire.py`. Change it there and nowhere else.

## Path files

```json
{
  "duration_s": 20,
  "person": [{"t": 0, "x": 0.5, "y": 0.5}, {"t": 5, "x": 1.5, "y": 1.5}, {"t": 15, "x": null}],
  "objects": [{"x": 1.0, "y": 0.15, "drop_db": 6}],
  "label_mode": "person",
  "meta": {"purpose": "train"}
}
```

The person walks in straight lines between waypoints and holds the last one.
`"x": null` means they left. `"person": null` is an empty room. Objects never move.
`label_mode` (default `person`) and `meta` (overrides for the `meta` message) are optional.

## Tests

```
pip install -r sim/requirements.txt
python -m pytest sim
```

## Ready-made paths

Use the short name: `python -m sim.fake zone_tour`.

| Name | What happens | Length |
|---|---|---|
| `zone_tour` | Walk in, stand 5 s in each zone (3, 4, 2, 1), walk out | 32 s |
| `stand_still` | Walk into zone 4 (10 s alert limit), stand still 15 s, walk out | 20 s |
| `empty_room` | Nobody there, noise only | 30 s |
| `metal_object` | Empty room, metal object next to `east`: a steady drop on both `east` links, `label_mode` object | 30 s |

## Replay a recording

```
python -m sim.fake zone_tour --fast > data/sessions/tour.jsonl   # record
python -m sim.replay data/sessions/tour.jsonl                    # play at real speed
python -m sim.replay data/sessions/tour.jsonl --speed 4 --loop
```

Replay waits between lines according to their timestamps (`recv_t` when the bus
recorded one, otherwise `t`). Lines come out with `"src":"replay"` and without
`recv_t`; nothing else changes. It works on real recorded sessions too. `data/sessions/` is git-ignored, so recordings stay local.
