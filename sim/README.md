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
`--loss 0.05` drops that share of messages after they are numbered, so `seq` has gaps like a
lossy radio (the first message always gets through). `sim.send` takes `--loss` too.

## Run the whole system with no hardware

```
python -m bus                          # in one terminal (and brain, web server, ...)
python -m sim.send zone_tour --loop    # in another
```

`sim.send` sends the same feed as `sim.fake`, one message per UDP datagram, to the
bus at `127.0.0.1:5600`, at real speed and stamped with the real clock. Give it a
recorded `.jsonl` file instead of a path name and it replays that file (`"src":"replay"`,
with `seq` renumbered from 1 because the whole file now comes from one socket).
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

Optional extras, all timed in seconds from the start:

| Key | Example | What it does |
|---|---|---|
| `objects[].t_on`, `t_off` | `{"x": 1.0, "y": 0.2, "drop_db": 10, "t_on": 25, "t_off": 55}` | The object is only there between those times |
| `router` | `[{"t": 45, "spot": "S-W30"}]` | Moves `pi5` to a contract router spot (`S-home`, `S-W30`, `S-E30`) |
| `outages` | `[{"node": "east", "t_on": 10, "t_off": 20}]` | A node (or one `"link"`) sends nothing in that window |
| `waves` | `[{"t_on": 14, "t_off": 16.5, "link": "pi5>unoq:wifi", "amp_db": 4, "hz": 2}]` | A waving hand: the link swings up and down |
| `camera` | `[{"t": 14, "state": "off"}]` | Camera state (`on`, `off`, `stalled`); labels stop unless it is `on` |
| `clipped` | `[{"t_on": 6, "t_off": 9}]` | The camera cannot see the person's feet: labels have `clipped: true` with `zone`, `foot_m` and `motion` null |
| `jumps` | `[{"link": "east>unoq:ble", "db": 9, "t_on": 5, "t_off": 12}]` | A link's level shifts by `db` with nothing in the room to explain it (`wobble_db` makes it unsteady) |
| `flickers` | `[{"t_on": 7.0, "t_off": 7.3}]` | Fake brain only: its decision says moving for that long while the person stands still |

## Hall links (optional, contract proposal in issue #358)

Two beacons far outside the square, `h` and `j`, as tripwires: for each long link the screen says
whether there is movement along that path. A hall link is a hall beacon heard by a receiver
(`h>unoq:ble`, `j>pi5:ble`, ...). A path gets them with a `hall` block; a path without one gives
exactly the output it always gave.

```json
"hall": {
  "beacons": {"h": [3.0, 19.0], "j": [-14.0, 6.0]},
  "walks": [{"tx": "h", "t_on": 35, "t_off": 38}, {"tx": "h", "rx": "unoq", "t_on": 77, "t_off": 80}]
}
```

- `beacons`: where each one is, in the square's frame (metres; far outside it).
- `walks`: somebody walks along a beacon's path between `t_on` and `t_off`. With `rx` only that
  receiver's link sees it; without, all of that beacon's links do. `drop_db` (default 8) is how deep the dip gets.
- `sent_hz` (default 25) and `heard` (default 0.3): each beacon sends that many adverts a second
  and a receiver hears that share of them, at uneven moments and far weaker than the square's links.
- `outages` with `"node": "j"` silence a hall beacon like any other node.

`sim.fake` and `sim.send` then also send the hall links' `rssi` (their own random stream, so the
core links' readings don't change). The fake brain (`sim.state`, `sim.ws`) adds `hall` to state:

```json
"hall":[{"id":"h>unoq:ble","tx":"h","rx":"unoq","xy_m":[3.0,19.0],"activity":1.0,"moving":true,"rate_hz":6.5,"stale":false}]
```

Like the rest of the fake brain it reads the answer from the script: `moving` while a walk is on the
link and for about 2 s after it, `stale` (with activity 0 and moving false) while the link has
fewer than 4 readings in 2 s. The real rule is in brain/hall.py.

The ready-made path is `hall/hall_walk` (90 s; it lives in `sim/paths/hall/`): quiet for 35 s, a
walk along h's path at 35 s, along j's at 47 s, j silent from 59 s to 69 s (stale), and at 77 s a
walk that only `h>unoq:ble` sees. A person stands in the square the whole time. The first walk
comes that late because the real brain needs about 25 s of a link before it knows its quiet level.

```
python -m sim.ws hall/hall_walk --loop       # the screen, with no board and no brain
python -m sim.send hall/hall_walk --loop     # through the real bus and brain
```

Until issue #358 lands, `contracts.check` rejects the hall `rssi` lines and the `hall` field.

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
| `wave_checkin` | Stand still in zone 4 past the 10 s limit, wave at 14 s (check-in), walk out | 25 s |
| `tray_t1` | Empty 25 s (baseline), metal tray at T1 for 30 s, then removed | 60 s |
| `router_move` | Tray at T1 from 25 s, router to `S-W30` at 45 s, tray gone at 60 s, router home at 65 s | 75 s |
| `dropped_link` | Person in zone 1; the east beacon is silent from 10 s to 20 s (sensor blind) | 30 s |
| `camera_unplug` | The zone tour with the camera unplugged at 14 s | 32 s |
| `clipped_feet` | Stand in zone 2 then zone 1; labels are clipped from 6 s to 9 s | 18 s |
| `demo` | The whole demo in order, for the fake brain (see below) | 64 s |
| `still_flicker` | Stand still in zone 4 with one 0.3 s moving flicker; the alert must still fire at 10 s | 18 s |
| `tamper` | Nobody there. Armed at 3 s (the path sends the cmd itself); the east beacon is unplugged from 10 s to 20 s: `tamper` at 13 s, `tamper_cleared` at 22 s; disarmed at 36 s | 40 s |
| `passed_by` | Nobody there. Armed at 3 s; at 10 s someone crosses the area in 1.5 s without stopping: `passed_by` once they are gone, no `intrusion`; disarmed at 21 s | 24 s |
| `step_in` | Nobody there. Armed at 3 s; at 10 s someone steps in and stands for 6 s: one `intrusion` about 3.5 s after stepping in; disarmed at 21 s | 24 s |
| `tray_removed` | Person in zone 2 throughout; tray at T1 from 5 s to 14 s, gone from the picture about 1 s later | 20 s |
| `lesson` | The live lesson (built from the layout in `sim/lesson.py`, no file): someone steps left and right, desk-view labels with no foot point, the camera unplugged at 45 s. The fake brain shows `model.training.lesson` ("learning: 6 of 10", then 8) from 25 s until the camera goes | 66 s |

## Replay a recording

```
python -m sim.fake zone_tour --fast > data/sessions/tour.jsonl   # record
python -m sim.replay data/sessions/tour.jsonl                    # play at real speed
python -m sim.replay data/sessions/tour.jsonl --speed 4 --loop
```

Replay waits between lines according to their timestamps (`recv_t` when the bus
recorded one, otherwise `t`). Lines come out with `"src":"replay"` and without
`recv_t`; nothing else changes. It works on real recorded sessions too. `data/sessions/` is git-ignored, so recordings stay local.

## Scrub a session before committing it

Recordings stay local (`data/sessions/` is git-ignored). To keep one, scrub it into `data/sessions/keep/`:

```
python -m sim.scrub data/sessions/s12.jsonl data/sessions/keep/s12.jsonl
python -m sim.scrub --check data/sessions/keep/s12.jsonl    # exit 1 if any identifier is left
```

It deletes fields that hold a device identifier (`mac`, `bssid`, `ssid`, `addr`, `name`,
`local_name`, `hostname`, ...) and blanks anything shaped like a MAC address in any other
text: bytes joined by `:`, `-`, `_` or `.`. Twelve hex digits in a row are blanked only under a
field whose name contains `mac`, `addr` or `bssid` (for example `src_mac`), because elsewhere they
look like any other hex, such as a short commit hash or the end of a UUID. Contract fields are never touched, so a scrubbed file still replays. It cannot spot a
device name hidden in a field with an unrelated name, so skim the file before committing.

## Fake brain state for the screen

```
python -m sim.state demo                 # real time, JSON lines on stdout
python -m sim.state wave_checkin --fast
```

Turns any path into the `state` (10 a second) and `event` messages of CONTRACTS.md section 5,
with `"src":"sim"`, so the room, HUD and game can be built before the real brain is ready.

This is a perfect brain: it reads the answer from the script instead of working it out from
radio, so it says nothing about how well the real one does. Anything a real brain would measure
(`model.train_s`, `model.ms_per_decision`, everything in `board`) is null.

It starts like a real one: `links` is empty until readings arrive, `xray` is null until the
baseline and `pred` is null until training. To keep paths short the fake baseline finishes 1 s in
and the fake training 2 s in, each with its event (`baseline_done`, `trained`).

From section 6 it follows: link health (stale, then SENSOR BLIND after 3 s, clear after 3 s ok;
the jump rule for a link more than 6 dB off its base for 3 s with nobody and nothing there, skipping
a steady drop below base), the still timer on smoothed decisions (it resets after 5 moving
decisions in a row or when another zone holds the majority of the last 10), an object leaving the
picture about 1 s after it is removed even with a person present,
`pred` null while blind or while the router is off `S-home`, the no-movement alert with the zone
limits, check-in on a wave, objects, the X-ray grid, and advice: an object that stays 5 s within
0.5 m of `pi5>unoq:wifi` gets an `advice` with a router spot, `before_dbm`, and `after_dbm` once
the router has moved (with the `advice` and `advice_result` events). `narration` is a fixed
template sentence for the latest event.

The `demo` path walks the whole story in order: walk in, wave a check-in, tray at T1 and the
advice, router moved and home, camera off, stand still until the alert, a wave that clears it,
a blind link, walk out (64 s).

To feed a browser, serve the same messages on the brain's WebSocket:

```
python -m sim.ws demo --loop             # ws://127.0.0.1:8765/ws
```

Every connected screen gets the same messages at real speed. `cmd` messages from the screen are
read: `reset_alert` clears the alert, `reset` also clears the still timer, check-in and advice,
sends the `reset` event and shows the narrator's template recap of the demo since the last reset,
`arm {on: true|false}` arms or disarms (section 6, Armed: `state.armed`, the `armed`,
`disarmed`, `intrusion` and `passed_by` events: an appearance still there `armed.hold_s` later
(nodes.json, 3 s) is one intrusion, one that is gone first is a `passed_by`; reset disarms), and the rest are accepted and ignored. The `arrival` path is the hero arrival: nobody,
then someone steps in on the left, crosses right and stands still. The `tamper` path is tamper while armed
(section 6, Tamper; wording in issue #533): `python -m sim.ws tamper --loop` arms by itself (a path's
`"commands": [{"t", "cmd", "args"}]` are run by the fake brain at their times), then east goes silent: the event
`tamper` with `info.node`, `state.tamper: ["east"]` with health blind and pred null, and `tamper_cleared` 2 s
after east is back. `state.tamper` is absent while no node is listed. Any path's `outages` with a `node` silence
every link of that node, so `{"node": "west", "t_on": 10, "t_off": 18}` unplugs another device. Options: `--host`, `--port`, `--rate`, `--seed`,
`--speed`, `--loop`. The crowd game page can point at it with `?ws=ws://127.0.0.1:8765/ws`; its
rounds count as practice because the source is `sim`.

## Demo rehearsal

```
python -m sim.rehearse          # PASS/FAIL per beat, exit 1 if any beat fails
python -m sim.rehearse --desk   # the 3-minute desk visit in docs/desk-demo.md
python -m sim.rehearse --lesson # the live lesson: teach left and right for 20 s, then unplug the camera
```

`--lesson` starts with a baseline, an empty recording and no model, sends the screen's commands
(`label_mode`, `record_start`, `train` with the recording still open, `record_stop`) and checks: a
model within 5 s of `train`, the learning signal, a second fit while the camera is on, one last fit
when it is unplugged, and then that the radio alone says left and right as the person keeps stepping.

Plays the whole demo, in runbook order, through the real bus and brain code and checks that each
beat reaches the screen's state or events: baseline, training, empty room, walk in, the four zones,
the no-movement alert, the wave check-in, camera unplugged, tray near the router, advice, router
moved and home, reset, and the narrator's end-of-demo recap (the template one, since there is no model). It prints how long each beat took to show.

Bus and brain are joined in one process and time follows the feed, so about three minutes of room
time runs in a few seconds. The UDP and WebSocket hops are not part of it. It needs the brain's
libraries (numpy, scikit-learn). The test runs it too, and every beat must pass.
