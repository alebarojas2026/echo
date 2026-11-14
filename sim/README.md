# sim

Fake radio data so everyone can test without hardware. Not used in the live demo.
Python standard library only (pytest for the tests).

Run everything from the repo root.

## Make fake data

```
python -m sim.fake my_path.json            # real time, JSON lines on stdout
python -m sim.fake my_path.json --fast     # all at once, for recording a file
```

Options: `--rate 15` (readings per link per second, 10-20), `--seed 0` (same seed, same data).

## The room

```
y=2 +-----n2-----+      zones:  2 | 3
    |  2  |  3   |              --+--
    n3----+-----n1              0 | 1
    |  0  |  1   |
y=0 +-----n0-----+
   x=0          x=2   (metres)
```

Four nodes at the midpoints of the sides, 6 links. A person near the line between
two nodes drops that link by up to 8 dB; every reading also has about 1 dB of noise.

## Output

One JSON object per line. Until the shared contract lands this is:

```
{"type":"rssi","t":1.2,"link":"n0-n1","rssi":-47}
{"type":"label","t":1.2,"zone":3,"present":true,"moving":false}
```

`t` is seconds since the start. `rssi` is dBm. Labels come about 5 times a second;
`zone` is `null` when nobody is there. The format lives in one function,
`encode` in `sim/wire.py`. Change it there and nowhere else.

## Path files

```json
{
  "duration_s": 20,
  "person": [{"t": 0, "x": 0.5, "y": 0.5}, {"t": 5, "x": 1.5, "y": 1.5}, {"t": 15, "x": null}],
  "objects": [{"x": 1.0, "y": 0.15, "drop_db": 6}]
}
```

The person walks in straight lines between waypoints and holds the last one.
`"x": null` means they left. `"person": null` is an empty room. Objects never move.

## Tests

```
pip install -r sim/requirements.txt
python -m pytest sim
```
