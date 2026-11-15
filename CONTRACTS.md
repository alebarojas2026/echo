# Contracts (v2.1: the desk layout, frozen)

The message formats every part of Echo agrees on. Only Ivan changes this file. Need a change? Open an issue labeled `contract`, keep working with what's here, and switch when the change lands.

v2.1 changes the layout only: section 3, and the places that named the old 2 x 2 m square, its four nodes, six links and four zones. Every message still carries `"v": 2`. Recordings, baselines and models made on the old layout don't fit this one.

All numbers in the examples below are made-up format examples, not measurements. Real results live only in proof.json and PROOF.md.

Every adapter (fake feed, readers, bus, brain, screen) speaks exactly this. At runtime, check only `v` and `type`; full schema checks run in tests and CI (contracts/).
state.src mirrors the inputs; the screen shows LIVE only for src live with nonzero link rates.

## 1. Envelope and units
```
Every message: {"v": 2, "type": <type>, "t": <producer epoch ms>, "seq": <per-producer counter, +1 per message>,
                "src": "live" | "sim" | "replay"}
bus/ adds "recv_t" (board epoch ms at arrival). Windows, label joins, scoring and proof use recv_t only.
A gap in seq from one producer = lost messages; bus/ counts them per producer.
  (Not for chain_head and chain_witness, section 13: their seq is a record number of the sealed record.)
Units: absolute signal in dBm (fields end in _dbm); differences in dB (_db); distances in m (_m);
  times in ms (t, *_ms) or s (*_s).
```

## 2. Hosts, ports and binds
```
Addresses:
- Board (UNO Q) hub Ethernet: 192.168.77.2/24. Pi A (pi5) eth0: 192.168.77.1/24. The one Ethernet cable carries
  Pi A's readings and the page data between Pi A and the board, and what Pi A forwards from the hotspot (Pi B's
  readings, the screen). Sensing itself is the only thing that never uses it.
- Sensing Wi-Fi: Pi A's 5 GHz hotspot, 10.42.0.1/24. The board's wlan0 gets DHCP from it.
- Pi B (pi5b) has no Ethernet address. Its wlan0 joins the sensing hotspot (DHCP from 10.42.0.1/24), and that
  link is itself a sensor (pi5>pi5b:wifi). Pi B's readings go to 192.168.77.2:5600 through Pi A, which forwards
  hotspot -> Ethernet (the hotspot's shared mode), so on the board they arrive from 192.168.77.1.
- Screen: a laptop on the sensing hotspot opens http://192.168.77.2:8080/?src=ws. Pi A routes it over the cable the
  same way. No monitor, no kiosk on a Pi. Only light traffic on the hotspot while the model runs: the page, never
  file copies.
Ports:
- bus: UDP 0.0.0.0:5600 on the board. Senders:
  - processes on the board send to 127.0.0.1:5600;
  - Pi A sends to 192.168.77.2:5600 over the cable; Pi B sends to the same address over the hotspot, through Pi A;
  - the App Lab camera teacher sends to msgpack-rpc-router:5600 (App Lab's host alias; gate 3 confirms it).
- bus -> brain: UDP 127.0.0.1:5601.
- brain: WebSocket ws://192.168.77.2:8765/ws (bound to 127.0.0.1 and 192.168.77.2 only).
- web: http://192.168.77.2:8080. board/serve.py serves web/dist (index.html goes out with
  <meta name="radio-sight-board" content="live"> added), /nodes.json and /proof.json, and answers POST /ask,
  GET /history and GET /report (section 10). Those three answer from the board's own records, need no internet and
  are reached on our own network only (the cable and the sensing hotspot).
  GET /chain, GET /chain/verify, GET /chain/tail and POST /chain/prove are the sealed record (section 13).
  GET /privacy is the live privacy meter (section 11). GET and POST /clock set the board's clock from the
  operator's laptop (section 12; as proposed, not built yet).
  It also has /layout for the operator's align mode: GET gives {"room": {offset_m, yaw_deg, scale, cut_m} | null,
  "hall_beacons": [{node, xyz_m}]} (every hall beacon in nodes.json; xyz_m is [x, y, z] or null). POST takes the
  same shape with either key or both (a room is never null there), JSON only, and only from the board itself,
  192.168.77.0/24 or 10.42.0.0/24; it answers like GET. It is saved on the board (data/layout.local.json) and is
  for drawing only: /nodes.json carries the saved hall xyz_m, and nothing else changes.
- llm: http://127.0.0.1:8091 (llama-server).
```

## 3. Nodes, links, frame and zones (radio/nodes.json, served as /nodes.json)
```
The desk layout: the sensing area is a strip of the judges' aisle against our desk, and every device sits on the desk.
Frame: metres. Origin = the strip's aisle-side west corner; x points east along the desk, y points north towards the desk.
  The strip is 1.6 x 0.6 m: 0 <= x <= 1.6, 0 <= y <= 0.6 (frame.strip_m). It is the only place a person stands.
  The desk top lies behind it: its judge edge is y = 0.6, its back edge y = 1.1.
  The whole layout is the rectangle 0 <= x <= 1.6, 0 <= y <= 1.1 (frame.size_m): the strip plus the desk top.
Nodes, every antenna 1.0 m high (the desk plus a 25 cm box):
  unoq  (1.1, 0.6, 1.0)   the board, at the desk's judge edge: receiver
  pi5   (0.8, 1.1, 1.0)   Pi A, at the desk's back edge: router (the hotspot) + beacon S + receiver
  pi5b  (0.5, 0.6, 1.0)   Pi B, at the desk's judge edge: beacon B + receiver
  east  (1.6, 0.25, 1.0)  ESP32 beacon E, on the tip of a cardboard arm over the aisle
  west  (0.0, 0.25, 1.0)  ESP32 beacon W, on the tip of a cardboard arm over the aisle
  A node in nodes.json may carry "device": the kind of hardware it is (unoq, pi5, esp32, phone). The screen picks
  the model it draws by device, never by matching the node's id. Missing, or a device the screen has no model
  for: a plain marker.
Link id = "<tx>><rx>:<kind>". Twelve links, always in this order (nodes.json, feature vectors):
   #  id              kind  tx    rx    where it runs
   1  pi5>unoq:wifi   wifi  pi5   unoq  over the desk
   2  pi5>unoq:ble    ble   pi5   unoq  over the desk
   3  east>unoq:ble   ble   east  unoq  across the strip, East
   4  west>unoq:ble   ble   west  unoq  across the strip, West and the middle
   5  east>pi5:ble    ble   east  pi5   the strip's east end
   6  west>pi5:ble    ble   west  pi5   the strip's west end
   7  pi5b>unoq:ble   ble   pi5b  unoq  along the desk's judge edge
   8  pi5>pi5b:wifi   wifi  pi5   pi5b  over the desk
   9  pi5>pi5b:ble    ble   pi5   pi5b  over the desk
  10  east>pi5b:ble   ble   east  pi5b  across the strip, East and the middle
  11  west>pi5b:ble   ble   west  pi5b  across the strip, West
  12  pi5b>pi5:ble    ble   pi5b  pi5   over the desk
  Two are Wi-Fi (1 and 8: the board's and Pi B's reading of Pi A's hotspot signal). Ten are Bluetooth.
  Links 1-6 keep the ids they had on the old layout; 7-12 are new with Pi B. All twelve are classifier links
  unless nodes.json says otherwise for one.
  Each link in nodes.json carries expected_hz, written after the baseline capture.
  A link may also carry "classifier": false (missing means true). It is for a link too thin to classify on: under
  4 readings a second at the baseline. Such a link is read and sent like any other, is listed in state.links, is
  judged by the stale and blind rules and counts for Tamper. But it never makes health blind, never goes into
  health.blind, never nulls pred, and is left out of feature vectors, pred.why, xray, objects, checkin and advice.
  The order and numbers of the twelve links do not change when one is switched off this way.
Zones: two, in the strip only, split at x = 0.8 (frame.zone_split_x_m).
  zone = 1 + (x >= 0.8) when 0 <= x <= 1.6 and 0 <= y <= 0.6; anywhere else 0 = empty.
  1 West "Left", centre (0.4, 0.3). 2 East "Right", centre (1.2, 0.3). The names are the sides as seen on the screen.
  zones: [{id, side, name, centre_m, still_alert_s}] with 1 -> 10, 2 -> 10.
  The desk top (y > 0.6) is never a zone: only objects are there (the tray), never a person.
router_spots: S-home (0.8, 1.1, 1.0), S-W30 (0.5, 1.1, 1.0), S-E30 (1.1, 1.1, 1.0): Pi A slides along the desk's
  back edge. Gate 7 sets the distance.
tray_spots: T1 (0.86, 1.0, 1.0).
Beacons are matched by manufacturer data FFFF 52 53 <'S' | 'B' | 'E' | 'W'>, never by MAC.
  S = pi5, B = pi5b, E = east, W = west.
  Gate 2 passes a Bluetooth link on what its beacon can give, never on a fixed number such as 20/s: the beacon is
  heard on at least 30% of its advertising events, and never under 7/s. A beacon sends one event every interval
  + 5 ms on average, and a scanner hears at most one copy of each. So E and W (ESP32, 35 ms) can give 25/s and pass
  at 7.5/s; S and B (a Pi, 20 ms) can give 40/s and pass at 12/s. radio/GATE.md has the procedure.
Hall links (optional): up to two more beacons far outside the layout, as tripwires.
  Hall beacons: manufacturer data FFFF 52 53 'H' and FFFF 52 53 'J' -> nodes h and j (beacon only, never a receiver).
  They live in nodes.json under "hall", with their positions (same frame, metres; may be many metres outside the
  layout; null until measured in the room).
  A hall beacon's xyz_m in /nodes.json is the one saved with /layout (section 2) when there is one; radio/nodes.json
  itself is not rewritten.
  A hall link is any link whose tx is a hall beacon: "<h|j>><rx>:ble" for every receiver rx in nodes.json
  (h>unoq:ble, j>pi5:ble, h>pi5b:ble, ...). The scanners send them as ordinary section 4 rssi messages (kind ble).
  The core links are the twelve listed in nodes.json "links". Hall links are never core links: they are not listed
  there and never appear in state.links, health, pred.why, xray, objects, checkin or advice.
  A hall link that has been calibrated is listed under "hall" too: "links": [{"id": "h>unoq:ble", "empty_quiet_db": n}]
  (optional). empty_quiet_db is that link's quiet level measured once with the hall empty (Hall activity, section 6).
Armed (optional): "armed": {"hold_s": n} = how long a person must stay before an intrusion is raised (Armed, section 6).
  Missing means 3. Use 4 for a very busy aisle.
Layout files: radio/layouts/<name>.json are whole layout files. python -m radio.use_layout <name> copies one over
  radio/nodes.json; radio/nodes.json is always a copy of one of them. The text above is radio/layouts/desk.json.
  The schemas list the union of the layout files (nodes, links, spots, the largest zone count), so a message of
  any of them passes its schema; what belongs to one layout (the length of probs, near) is checked against the
  layout in use, radio/nodes.json (contracts/check.py; --layout <name> names another).
The gate layout (radio/layouts/gate.json): one spot between Pi B and the desk. Frame: metres. Origin = the spot's
  west corner on the side away from the desk; x east along the desk, y north towards the desk.
  The spot is 0.8 x 0.6 m: 0 <= x <= 0.8, 0 <= y <= 0.6 (frame.strip_m). It is the only place a person stands.
  frame.size_m (0.85 x 1.35) is the box the screen and the x-ray grid are laid out on, from the origin to the back
  of the desk top. size_m + 0.4 m is a whole number of 0.125 m cells. A node may sit outside size_m and outside
  the spot (Pi B is at y = -0.2); every reader accepts that.
  Nodes (rough until measured): unoq (0.44, 0.8, 0.75) the board; pi5 (0.36, 0.8, 0.75) Pi A, the router;
  pi5b (0.4, -0.2, 0.75) Pi B. The desk's edge is y = 0.8. No east, no west, no hall beacons.
  Six links, in this order: pi5>unoq:wifi, pi5>unoq:ble, pi5b>unoq:ble, pi5>pi5b:wifi, pi5>pi5b:ble, pi5b>pi5:ble.
  A link may carry "crosses_spot": true | false. true = a person on the spot stands in this line (here: the four
  to or from Pi B). Missing means the layout does not say (the desk strip). The brain uses the marked lines for
  the rules in section 6; the screen draws its signal trace from them, whatever radio they are.
  Zones: a strip with no frame.zone_split_x_m and one zone is one spot: zone = that zone's id when 0 <= x <= strip
  width and 0 <= y <= strip depth; anywhere else 0. zones: [{id, name, centre_m, still_alert_s}]; "side" is optional.
  1 "At the desk", centre (0.4, 0.3), still_alert_s 10.
  "presence" (optional): {"line": <link>, "second": <link>, ...} names the one line that decides whether somebody
  is on the spot and the numbers of its rules (Presence line, section 6; "second" is no longer used). Both are lines of
  the layout marked crosses_spot. The gate: line pi5>pi5b:wifi.
  The router does not move on the gate (Pi A is cabled to the board's hub): router is always S-home, and advice
  never names a spot (to_spot null, section 5).
  gate-3 (radio/layouts/gate-3.json) is the gate cut down to three links, for a kit that can't give all six; the
  file lists them. Everything else is the gate's.
  Gate 2 on these layouts: a Bluetooth link passes at 30% of its beacon's advertising events and never under 2/s
  (the kit gives 2 to 6/s on a metre-long line). The presence line must arrive 20 times a second or more at the
  brain: nothing between Pi B's reader, the bus and the brain may thin it.
Code takes ids, positions, links, zones and spots from nodes.json, not from constants of its own.
```

## 4. Inputs to the bus
```jsonc
{"v":2,"type":"rssi","t":1763149512120,"seq":881,"src":"live","link":"east>pi5:ble","kind":"ble","tx":"east","rx":"pi5","dbm":-61}
{"v":2,"type":"label","t":1763149512150,"seq":412,"src":"live","frame":18231,"mode":"person","persons_in_frame":1,
 "present":true,"zone":2,"foot_m":[1.22,0.31],"motion":"moving","conf":0.81,"clipped":false}
   // One label per processed camera frame (5-10/s), including frames with nobody in them.
   // present:false only on a processed frame with nobody in the sensing area (floor view: no foot point inside the
   // strip; desk view: nobody in view); then zone 0, foot_m null, motion null.
   // Desk view (the webcam on the desk, facing the person): there is no foot point. foot_m is null on every label;
   // present is true when anyone is in view, and zone is the side of the split line the person's box centre is on.
   // clipped is true when the centre is within the dead band around the line, the box is cut by a side edge of the
   // frame, or more than one person is in view.
   // With one zone (the gate) there is no split line and no dead band: zone is that zone whenever present is true,
   // and clipped is true only when the box is cut by a side edge or more than one person is in view.
   // seq: one counter per sending socket (a producer), shared across all message types it sends.
   // clipped:true -> zone, foot_m and motion are null, whatever present is, and the window is dropped. mode = the current label_mode.
{"v":2,"type":"cam","t":1763149512200,"seq":77,"src":"live","state":"on","fps":9.6}
   // From teacher/camwatch.py: every 1 s and at once on any change. state = on | off | stalled.
{"v":2,"type":"narration","t":1763149513000,"seq":9,"src":"live","text":"Someone just walked into zone 2.",
 "event_id":"e123","event_kind":"enter","gen_ms":6120,"source":"llm","model":"<model name>"}
   // source = llm | template. model is null when source is template.
   // event_kind "recap" = the end-of-demo recap, sent when the brain's reset event arrives. The reset has already
   // cleared narration, so the recap is the first narration after it (up to 45 words, see section 6).
{"v":2,"type":"meta","t":1763149500000,"seq":1,"src":"live","session":"s12","purpose":"heldout","walker":"w3"}
   // Sent on record_start. purpose = train | heldout | object | crowd | demo
```

## 5. Brain -> screen (WebSocket, about 10 state messages a second)
```jsonc
{"v":2,"type":"state","t":1763149512200,"seq":5012,"src":"live","cam":"on","router":"S-home",
 "links":[{"id":"east>pi5:ble","dbm":-63.0,"base_dbm":-58.1,"drop_db":4.9,"rate_hz":9.2,"expected_hz":9.5,"status":"ok","why":0.42}],
 "health":{"status":"ok","blind":[],"reason":null},                         // status ok|degraded|blind; reason rate|jump
 "pred":{"present":true,"kind":"person","zone":2,"zone_set":[2],"probs":[0.04,0.11,0.85],
         "motion":"still","still_s":4.2,"why":["east>unoq:ble","east>pi5b:ble"]},
        // probs = [empty, z1, ...]: one entry for empty, then one per zone in nodes.json. kind = person | object | none.
        // The desk has two zones: [empty, z1, z2]. With one zone (the gate): [empty, z1], zone is 1 when present
        // and zone_set is [1].
        // pred is null before training, while health is blind, while recalibrating, and while the router is off S-home.
        // On a layout with a presence line pred needs no training: it is there from the first baseline (section 6).
        // present:false -> zone 0, zone_set [], motion null. present:true -> motion is moving or still.
        // Not sure where: when somebody is there but the links read unlike anything in training (a feature more than
        // 6 dB outside what the model saw), zone_set lists every zone the model knows. zone is still its best guess.
        // That is the only way pred says "not sure". There is no separate field for it, and present:false is never
        // qualified: nobody is there, or pred is null.
 "objects":[{"xy_m":[0.86,1.0],"near":"pi5","since_s":14.0,"drop_db":9.8}],
        // near (here and in advice) = the closest node within 0.5 m of xy_m, or null when no node is that close.
        // Node positions are where the nodes are now: the router at its current spot after router_moved.
 "xray":{"w":16,"h":12,"cell_m":0.125,"origin_m":[-0.2,-0.2],"moving_db":[/* w*h */],"static_db":[/* w*h */],"n_links":12},
        // The screen draws whatever w x h it receives. Cells are row by row from the south edge:
        // index = iy*w + ix, ix east from origin_m[0], iy north from origin_m[1]; cell centre = origin_m + (i+0.5)*cell_m.
 "alert":{"state":"counting","zone":2,"still_s":7.2,"limit_s":10},          // none|counting|check_on
 "checkin":{"t":1763149511000,"link":"pi5>unoq:wifi"},                       // the last check-in, or null
 "advice":{"id":"a7","cause":"obstruction","near":"pi5","xy_m":[0.86,1.0],"link":"pi5>unoq:wifi","to_spot":"S-W30",
           "move_m":[-0.3,0.0],"dist_change_m":0.2,"text":"An obstruction next to the router is blocking its link to the receiver. Move the router 30 cm west.",
           "before_dbm":-71.2,"after_dbm":null,"why":["pi5>unoq:wifi","east>pi5:ble"]},   // or null
        // to_spot is null on a layout with a presence line: the router stays where it is, so there is nothing to
        // move. Then move_m is [0, 0], dist_change_m is 0, link is the presence line, and after_dbm is measured
        // when the thing is taken away (Advice, section 6). Every field is there as before; none is new.
 "narration":{"text":"...","event_id":"e123","t":1763149513000,"source":"llm","gen_ms":6120},
 "teacher":{"present":true,"zone":1,"motion":"still"},                       // null when the camera is off
 "hall":[{"id":"h>unoq:ble","tx":"h","rx":"unoq","xy_m":[14.0,9.5],"activity":0.62,"moving":true,"rate_hz":6.5,"stale":false,
          "busy":false}],
        // Optional: may be missing, and a screen reads a missing hall as []. One row per hall link once it has a reading,
        // by receiver in nodes.json order, then by beacon. xy_m = the far beacon's position (the tx end), or null when
        // nodes.json has none; the other end is the rx node. activity is 0-1. rate_hz = readings over the last 2 s.
        // It means "movement on this path": never who, where along it, or how many. stale:true -> activity 0, moving false.
        // busy is optional and missing means false. busy:true = too much foot traffic on the path to pick out one
        // movement (Hall activity, section 6); then moving is false. A stale row is never busy.
 "model":{"trained":true,"ver":"m3","train_s":8.4,"ms_per_decision":3.1,"windows":612,"train_sessions":["s07","s08"],"training":null},
        // training is null unless a fit is running or a lesson is on. While a fit runs:
        //   {"started_t": epoch ms, "progress": 0..1 or null, "sessions": [ids]}.
        // A lesson = a train cmd that arrives while a record_start {purpose: train} recording is open. From then on
        // the brain fits again from the growing recording, 15 s after each fit ends, while cam is on, and training
        // stays set with
        //   "lesson": {"started_t": epoch ms, "agree": 6, "of": 10, "fits": 2, "fitting": false}
        // added to it (between fits: started_t = the lesson's start, progress null, sessions = [the lesson's recording]).
        // agree / of: of the last `of` decisions (10 at most) that had a fresh, non-clipped camera label, `agree` gave
        // the camera's answer (same zone, or both nobody). fits = fits finished in this lesson; fitting = one is running.
        // The lesson ends when cam goes off or on record_stop: one last fit runs, training goes back to null, and
        // the model carries on.
        // train_s and ms_per_decision are null when nothing was measured (the fake brain), even when trained is true.
 "armed":false,                                                             // true after arm {on:true}; missing means false
 "chain":{"seq":4127,"hash8":"1a2b3c4d","verified":true,"witnesses_ok":2,"witnesses":2},   // optional: the sealed record in short (section 13)
 "tamper":["east"],                                                         // optional: the nodes silent while armed (Tamper,
                                                                            // section 6); missing or [] when there is none
 "board":{"cpu_temp_c":57.0,"cpu_mhz":2016,"cpu_pct":61}}
{"v":2,"type":"event","t":1763149512200,"seq":120,"src":"live","id":"e123","kind":"enter","info":{"zone":2}}
   // kinds: enter, exit, zone_change, checkin, object_on, object_off, advice, advice_result, router_moved, router_home,
   // recalibrating, cam_off, cam_on, cam_stalled, alert_on, alert_off, blind_on, blind_off, trained, baseline_done, drift,
   // reset (after the reset cmd), recording (info: {on, session}) after record_start/record_stop,
   // armed, disarmed, intrusion (info: {zone} or {link} for a hall link), passed_by (info: {zone}),
   // tamper, tamper_cleared (info: {node}, e.g. {"node":"east"}; a hall beacon is h or j).
   // info carries what the narrator needs: zone, link, node, before_dbm, after_dbm.
   // alert_off on a layout with a presence line also says why: checkin | moved | left | reset.
```
Before readings, a baseline or training exists, the brain still sends state at about 10/s with these values:
- links: [] until readings arrive (never null). A link is listed once it has at least one reading (dbm is then a number);
  before the baseline its base_dbm, drop_db and expected_hz are null, and status is "ok" or "stale" from its rate;
- xray: null before the first baseline;
- objects: [], advice: null, checkin: null, narration: null until each exists;
- alert: {"state":"none","zone":null,"still_s":0,"limit_s":null} when nothing is counting;
- model: {"trained":false,"ver":null,"train_s":null,"ms_per_decision":null,"windows":0,"train_sessions":[],"training":null} before training;
- board: any field it can't read is null.

**Screen -> brain:**
```jsonc
{"v":2,"type":"cmd","cmd":"train|baseline|reset_alert|reset|record_start|record_stop|label_mode|router_moved|router_home|relearn|truth|arm","args":{}}
   // record_start {session, purpose, walker}; label_mode {mode: person|object|off}; router_moved {spot}; truth {zone} (crowd game).
   // reset = between judges: clears the alert, still timer, check-in, advice and narration.
   // train while a train recording is open also fits from that recording as far as it has got, and starts a lesson
   // (see model.training).
   // arm {on: true|false} = "this space should be empty now" (after hours). See Armed in section 6.
   // baseline {} = a new place: the model and the older recordings are no longer used. baseline {keep_model: true} =
   // the same place set down again (the same layout at another desk, a knocked arm): only the baseline is new. Section 6.
```

## 6. Shared rules (every part computes the same thing)
```
Windows: 1.0 s long, 0.1 s hop, on recv_t. A window's label is the majority of the non-clipped camera labels in it.
  Windows with a clipped label or with no label are dropped from training.
Moving: foot speed > 0.25 m/s over 1 s, after a 0.5 s median filter. In the desk view the speed is that of the
  box centre along the strip.
Baseline: a 20 s capture with health ok, persons_in_frame == 0 from the camera, and label_mode off.
  With the camera off (unplugged at the judging desk) there is no camera to ask: the capture runs on health ok and
  label_mode off alone, and the operator keeps the strip empty.
  A baseline started by the `baseline` cmd means a new place. On its baseline_done the brain drops the model (pred is
  null and model.trained is false until the next train), and train and relearn use only sessions recorded after it.
  Older session files stay in data/sessions and are never trained on again. The brain writes data/sessions/place.json:
  {"t": epoch ms of that baseline_done}. The automatic baseline after router_home ("recalibrating") keeps the place:
  the model, the recordings and place.json stay as they were. proof/ scores only sessions whose meta recv_t is at or
  after place.json's t.
  While a plain `baseline {}` (a new place) runs, no link is stale by rate; the capture sets expected_hz again.
  A link with no reading for 1 s restarts the capture, as it does for the automatic baseline.
  For baseline {keep_model: true}, only a link silent for 3 s, or health blind, restarts the capture. A stale link
  does not: the capture also runs while health is degraded, and links are still judged against the old expected_hz
  until it ends. (The same layout set down at a new desk, in a hall full of phones, must be able to finish.)
  A baseline asked for by the `baseline` cmd (with or without keep_model) that still cannot start 120 s after the cmd
  is given up: nothing changes and pred returns. The old baseline, the model and the recordings stay. There is no
  event for it; the brain logs why it never started. A capture that is running at 120 s goes on, and is given up if
  a condition then breaks. The automatic baseline after router_home keeps waiting.
  baseline {keep_model: true} is the exception to "a new place": it is the same place set down again, so, like the
  automatic baseline, it keeps the model, the recordings and place.json and only the baseline is new. The model was
  taught on drops from a baseline, so it carries over to a new baseline of the same layout; features are taken
  relative to the baseline for this reason.
  On baseline_done the brain writes data/sessions/baseline.json: {"t": epoch ms, "session": id or null,
  "links": {link id: {"base_dbm": n, "expected_hz": n}}}. proof/ and a brain restart read it from there.
  On trained the brain writes data/sessions/model.pkl (a Python pickle: {"ver", "base": {link id: base_dbm},
  "place_t", "model"}). At start the brain loads it only if its place_t equals place.json's t (a file without
  place_t: only if its base equals baseline.json's) and it was fit on this layout's links and zones; otherwise it
  starts untrained. Nothing else reads this file.
  Every baseline, by hand or automatic, is also appended to data/sessions/baselines.jsonl: one line
  {"t": epoch ms, "base": {link id: base_dbm}}. train reads each recording against the baseline that was in force
  when it was recorded, so recordings from before a keep_model baseline still fit.
Link health:
- A link is stale when its rate over the last 2 s is < 0.4 x expected_hz.
- It is blind when stale for >= 3 s, or when pred.kind == none and |median - base| > 6 dB for >= 3 s.
  The jump rule (the second one) is off while the router is off S-home or a baseline is running. It doesn't apply to a link
  whose reading is below its base and steady: the std of its 0.5 s means, over the time since it went off base (2 s at least,
  5 s at most), is < 0.8 dB. A steady drop is an object, not a broken link. Above base, or off base and not steady, is still a jump.
- health is blind when any classifier link is blind. Then pred is null and the screen shows SENSOR BLIND (never "empty").
  A link with "classifier": false in nodes.json (section 3) is not one: stale or blind, it shows it in state.links
  and health.status is then degraded, as for the links Pi B hears below.
- A link whose baseline counted under 4/s is judged on rate only once its expected_hz is 4/s or more. Below that it
  shows status stale while it reads under 0.4 x expected_hz, but is never blind by rate.
  Alert timers pause. It clears after 3 s ok.
- The links Pi B hears (rx pi5b: links 8, 9, 10 and 11) are the exception. Their readings reach the board over the
  hotspot, which can lose packets for reasons that have nothing to do with the radio path. Each of them is still
  judged stale or blind by the rules above and shows it in state.links, and health.status is then degraded; but they
  never make health blind, never go into health.blind, never null pred and never pause the alert timers.
Baseline, the empty level follows slow drift: on a layout that marks crossing lines, the baseline of each crossing
  line follows slow drift. While pred.present is false, its base_dbm moves towards the line's median over the last
  1 s window with a time constant of 30 s (brain/settings.py drift_follow_s; 0 = the fixed baseline). It stops the
  moment the crossing lines' median drops, averaged, reach 2 dB (or 1 x their quiet level), or the presence line's
  own drop reaches 2 dB, and stays stopped while pred.present is true: a person standing still is never absorbed,
  however long. If pred.present has been false all through a dip of 30 s, following starts again (the room
  changed, not a person), except while the decision is "object". The other links keep the captured baseline. The
  followed level is kept in baselines.jsonl ({"t", "base"}, at most one line every 10 s and only after a 0.5 dB
  move) so a recording is read against the level in force when it was made. baseline.json keeps the captured
  values: after a restart take a new baseline.
Presence on a layout that marks crossing lines and has no presence line: the model's features also hold each
  crossing line's median drop over the window and the average of them. Arriving is the model's decision alone.
  Leaving has a hold: once pred.present is true, it stays true while the crossing lines' median drops, averaged,
  are 3 dB or more (or 1.5 x their quiet level; stay_x_quiet).
Object (a training label): only in label_mode object. Every frame must have persons_in_frame == 0, and one or more
  links must drop >= 3 dB for >= 2 s with the std of their 0.5 s means < 0.8 dB.
Presence line (only on a layout whose nodes.json has "presence"; every number is a key of that block, with the
  default given here, and the kit's own numbers go in the file):
- Drop = the line's baseline minus its median over the 1 s window. Somebody is there once the drop reaches on_db
  (7 dB), and stays until it is under off_db (4 dB). The model still gives probs, but it does not decide present.
- No model and no lesson are needed (the camera is not used in the demo): after a baseline, with no model
  trained, pred is the line's word alone. present true is kind "person" in the layout's zone (zone_set that
  zone), probs is [0, 1] (present) or [1, 0] (nobody), why is the line, and moving or still, a thing left in
  the line, still_s, the alert, the check-in, armed, intrusion and passed_by all follow as below. model says
  trained false; pred is never null for that reason. A trained model still gives probs and why, as before.
- No other line has a say (decided from the kit's recordings: its Bluetooth lines dip 9 to 20 dB with nobody
  there, and the short Wi-Fi line on the desk climbed 9 dB over one run). "second" may stay in the file and is
  not used. While the line has no readings its last word stands for second_hold_s (5 s), and then it is nobody.
- Health on such a layout comes from the presence line alone: health is blind only when that line is stale or
  silent (the rate rule of Link health; the 6 dB jump rule is off for every link). The other lines stay in the
  file, are drawn, show stale in their own rows (health degraded) and count for tamper when their device goes
  quiet; their level never makes the sensor blind, never raises "object" or advice, and never decides present.
  A layout with no presence line keeps every rule it had.
- The drift follow (Baseline) reads the presence line alone on such a layout: where that rule says "the crossing
  lines' median drops, averaged", it is this line's drop, and only its empty level follows drift (the other lines
  keep the captured baseline).
- Check-in on such a layout: "step aside and back" (leaning does not take a body out of the line). While the
  alert is check_on, pred.present ending for 0.3 s or more and starting again within checkin_return_s (8 s) is one
  checkin event ({zone, link: the presence line}); it clears the alert and the still timer starts again. Not back
  within checkin_return_s is the person leaving: alert_off with why "left", no checkin. On screen and in the
  narrator: "Step aside and back to say you're okay".
- Alert on such a layout: one decision, no smoothing. still_s counts only while pred is present, kind person and
  motion still. motion moving (already steady, see below) puts it back to zero and clears an alert (alert_off, why
  "moved"). With nobody there nothing counts and alert is the empty block at once, even while the brain still
  waits checkin_return_s for a step back. So in any state message alert.state counting or check_on means pred is
  present, a person and still, and pred.motion moving or pred.present false means alert.state none. alert_off
  says why: checkin | moved | left | reset.
- Spread = the std of the line's readings over the last 2 s. The line arrives 25 times a second and sits within
  1 dB when the spot is empty, so the spread tells a body (it wobbles) from a thing (it does not).
- Moving and still: the word is steady. motion becomes "moving" once the spread has stayed at or over the boundary
  for motion_hold_s (1.5 s), and "still" again once it has stayed under still_spread_db (0.8 x the boundary unless
  the file says) for as long; between the two it stands. Somebody who has just stepped on starts as still, and the
  spread never includes readings from before they stood there. The boundary is moving_spread_db (2 dB) until a lesson has given 20 or more windows of
  each kind on this line; then it is the value that best splits that lesson's moving and still windows, kept
  with the model. The Bluetooth lines have no say in it.
- A thing left in the line: the 2 s median drop is object_db (3 dB) or more and under object_max_db (10 dB; null
  in the file = no upper limit), and the spread is at most object_spread_db (1 dB: the empty level's own jitter),
  for object_hold_s (3 s). Then pred is present false, zone 0, kind "object": no enter, no still timer and no
  intrusion. It ends 1 s after either stops holding. A drop of a person's depth (object_max_db or more), or one
  that wobbles, is a person however long they stand: a person on the spot is never an object and never a dead zone.
- While the decision is "object" the line's empty level does not follow drift (Baseline), so the gain can be
  measured against it when the thing is taken away.
Check-in (a rule, not learned): on pi5>unoq:wifi, >= 4 alternating crossings of +/-1.5 dB around the 1 s rolling median
  within 2.5 s, with pred.zone unchanged and no other link's drop changing by > 3 dB. Gate 8 tunes the thresholds.
Check-in on a layout that marks crossing lines (a rule, not learned; the wave above stays for the others): "lean
  aside". While the still timer is counting or the alert is on, the crossing lines' median drops, averaged, come
  back up towards the empty level by 4 dB (or 2.5 x their quiet level; lean_x_quiet) and by at least half of what
  the person standing there took off them, stay up for 0.3 to 2.5 s, and drop again. That is one checkin event
  ({zone, link: the first crossing line}) and it clears the alert. Up for longer than 2.5 s is the person leaving:
  an alert that was on ends (alert_off), with no checkin. On screen and in the narrator: "Lean aside to say
  you're okay".
Alert:
- On a layout that marks crossing lines the still timer resets on moving only after 30 moving decisions in a row
  (3 s; spot_moving_run), not 5. The alert means "somebody has been here for N seconds with no clear burst of
  movement"; the screen claims no more.
- still_s counts while kind == person, motion == still and the zone is unchanged, judged on smoothed decisions:
  it resets only after 5 moving decisions in a row (0.5 s), or when another zone or kind holds the majority of the last 10 decisions.
- check_on when still_s >= zones[zone].still_alert_s. null never alerts, and objects never alert.
- It clears on a checkin or on reset_alert.
Armed (after hours: the space should be empty):
- arm {on:true} sets state.armed and sends the event armed; arm {on:false} or reset clears it and sends disarmed.
- While armed, a person appears when pred.present is true with kind person for the majority of the last 10
  decisions, after it was not. Still there 3 s later: one intrusion event, naming the zone. Gone first (not present
  for the majority of the last 10 decisions): a passed_by event instead, naming the zone. Objects raise neither.
  The 3 s is armed.hold_s in nodes.json (default 3; 4 for a very busy aisle).
- While health is blind or pred is null, no intrusion and no passed_by is raised and the screen says so (never
  "all clear"). An appearance that is still waiting then is judged once pred is back.
Tamper (a rule, not learned; while armed only):
- A node is silent when every link it sends or receives on has had no reading for 3 s. This is its own test on the
  readings, not the blind rule: it does not wait for a link to be judged stale or blind, it counts Pi B's links
  (which never make health blind) like any other, and it goes on while health is blind and pred is null. A silenced
  node usually blinds the sensor as well, so the tamper is what is still reported then.
- While armed, a node that goes silent raises the event tamper once and is listed in state.tamper. Arming while a
  node is already silent raises it at once.
- It clears when all of that node's links have been fresh (the last reading at most 1 s old) for 2 s: the event
  tamper_cleared is sent and the node leaves state.tamper. Its links to another node that is itself still listed
  are left out of this, as long as one link remains, so two devices can come back one at a time.
  Disarming (arm {on:false} or reset) clears every listed node the same way.
- Not armed: no tamper events and no state.tamper (the screen still shows the device as not heard).
- The optional hall beacons count as nodes here (h, j), each once it has been heard since arming. This is the one
  place a hall node appears outside state.hall.
- The screen never says "all clear" while state.tamper is not empty.
Hall activity (a rule, not learned; per hall link, from that link's readings only):
- spread_db = the std of the link's 0.5 s means over the last 3 s.
- stale when fewer than 4 of those six 0.5 s bins hold a reading (the readings stopped, or are too few to judge);
  it clears after 3 s not stale. While stale: activity 0, moving false, and the screen draws nothing for the link.
- quiet_db = the link's own quiet level: the 20th percentile of spread_db, sampled once a second while not stale,
  over the last 5 min. It needs 20 samples (before that: activity 0, moving false) and is never under 0.5 dB.
- activity = (spread_db / quiet_db - 2) / 4, held to 0-1 (0 up to twice the quiet level, 1 at six times).
- moving turns true when activity >= 0.5 (four times quiet), and false again after activity has stayed < 0.25
  (three times) for 1 s.
- empty_quiet_db (nodes.json, per hall link) is the link's quiet level measured once with the hall empty. While
  quiet_db, the link's current quiet level, is above twice that, the path is busy: moving is false, busy is true, and
  the screen says "path busy" (never "movement on this path", never "clear"). Stale comes first: a stale link is
  not busy.
- Without an empty_quiet_db the brain still sends the row as above, with no busy, but the screen never shows that
  link as anything but "not calibrated".
- The thresholds are first values, tuned at the hardware test (#95).
X-ray:
- The grid covers the whole layout rectangle (frame.size_m: the strip and the desk top, 1.6 x 1.1 m) plus 0.2 m on each
  side: x from -0.2 to 1.8, y from -0.2 to 1.3. The brain sends 16 x 12 cells of 0.125 m with origin_m [-0.2, -0.2].
  The desk top is inside the grid because the tray and the router's link are there.
- Weights per Wilson & Patwari: 1/sqrt(link length) inside an excess path <= 0.1 m.
- P = (W^T W + alpha I)^-1 W^T, computed at startup and again on router_moved and router_home.
- Per link, static_db = the drop that has held >= 5 s with the std of its 0.5 s means < 0.8 dB (raw readings are too noisy), updated ONLY while pred is not null and
  pred.kind != person (frozen while a person is present), so a person standing still never becomes an "object".
- Lowering is not frozen: when a link's current drop (1 s median) has sat at least 2 dB under its static_db for 1 s, static_db
  comes down to that drop, whatever pred says. An object whose link has just come down is dropped from objects at once.
- The people part per link = max(0, drop_db - static_db). xray.static_db = the image of the static parts;
  xray.moving_db = the image of the people parts.
- Static means "appeared since the baseline", never walls.
Advice:
- Fires when an object persists >= 5 s and its static_db peak lies within 0.5 m of pi5>unoq:wifi.
- Only while pi5>unoq:wifi is dropping now: its drop_db in state.links is at least 3 dB. No row, or a null drop, means no advice.
- Picks the router spot (not S-home) whose new link has the lowest summed static_db along its ellipse.
- The pick is made when the advice first fires. While advice keeps coming for an object within 0.5 m of it,
  its id, spot and text stay as they were; only before_dbm is kept current. It's picked again only after
  the advice goes away or is about another object. A reset dismisses the advice for that object until it goes away.
- The text is built from the result, never a fixed string.
- before_dbm = median of pi5>unoq:wifi over the last 3 s: kept current while the advice shows, frozen at router_moved, never null.
- after_dbm = median over 3 s, starting 2 s after router_moved.
- On a layout with a presence line (the router is cabled and does not move) the advice is about that line and
  names no spot: it shows while the decision is "object" (a thing left in the line, above), with link = the
  presence line, to_spot null, move_m [0, 0], dist_change_m 0, and xy_m = the x-ray's object on that line, or the
  middle of the line. The text says something is standing in the line and never says to move the router.
  before_dbm = the line's median over the last 3 s, kept current while the thing is there. When the thing is taken
  away (the decision is no longer "object" and the line's drop is under object_db), after_dbm = its median over
  3 s, starting 2 s later, and advice_result {link, before_dbm, after_dbm} is sent: the gain is after_dbm -
  before_dbm. The advice then stays 10 s and goes. If somebody steps on the spot instead, the advice goes at once.
Router: take the tray off and put Pi A back on S-home BEFORE sending router_home. While the router is off S-home, pred is null. On router_home, every pi5 link must sit within 1 dB of base
  for 3 s (a pi5 link has pi5 as its tx or rx: links 1, 2, 5, 6, 8, 9 and 12; pi5b is a different node); otherwise the board runs an automatic 20 s baseline ("recalibrating").
Narration:
- At most one narration every 8 s, a recap included: the sentence after a recap waits 8 s.
- An event's template sentence is sent at once, always. If the on-board model's wording of it is back within 2 s, it is sent
  as a second narration with the same event_id and replaces the first; that second one does not count towards the 8 s.
- Only for an event <= 3 s old.
- At most 16 words (a recap: at most 3 sentences and 45 words). A banned word -> use the template sentence instead.
Screen: NO DATA (grey) when the last state is > 1 s old (the feed is stale). SENSOR BLIND when health is blind
  (the radio failed). These are different states.
```

## 7. proof.json (served as /proof.json)
The values below show the format only; they are not results.
```jsonc
{"zone":{"correct":47,"total":52,"ci95":[0.79,0.96],"sessions":["s21","s22"],"walkers":5,"method":"held-out, see PROOF.md"},
 "threshold_zone":{"correct":38,"total":52},
 "person_vs_object":{"correct":null,"total":null,"tray_placements":null},
 "false_alarms_per_min":null, "train_s":8.4, "ms_per_decision":{"p50":3.1,"p95":4.0},
 "watts":{"idle":null,"teaching":null,"radio_only":null,"source":null},
 "bytes_out":0, "images_stored":0, "models_on_board":3, "measured_at":"...", "commit":"...",
   // bytes_out = bytes sent to the internet over the measured run. The privacy claim is "nothing is sent to the
   // internet", never "nothing leaves the board": our own laptop and phone, on our own network, receive the
   // screen's data.
 "security":{
   "detection":{"entries":null,"detected":null,"ci95":null,"armed_entries":null,"intrusions":null,"intrusion_ci95":null,"within_s":2},
   "false_alarms":{"presence_events":null,"intrusions":null,"duration_s":null,"armed_duration_s":null,
                   "presence_per_hour":null,"intrusions_per_hour":null},
   "fewer_devices":[{"name":"...","nodes":["unoq","pi5"],"links":["pi5>unoq:wifi"],
                     "zone":{"correct":null,"total":null},"presence":{"entries":null,"detected":null,"ci95":null}}]}}
   // A number not yet measured is null. Never invent one. PROOF.md, the docs and the operator's view show it as "__".
   // The judge-facing screen leaves its tile out (section 8). A measured 0 is a number and is shown.
   // security is optional (the whole object may be missing). Every unmeasured value in it is null.
   // detection: entries are independently labeled empty -> present transitions; a trial counts only with continuous
   //   truth and captured predictions through the deadline (within_s). Intrusion trials also need captured armed coverage.
   // false_alarms: the denominators cover independently labeled-empty time overlapping captured healthy states;
   //   no capture or no exposure stays null.
   // fewer_devices: one row per subset of nodes and links (ids from radio/nodes.json). Each has its own model, trained
   //   on the training sessions with the other links masked, and is scored only on separate heldout sessions.
```

## 8. Screen test ids
```
source-badge, cam-status, pred-zone, pred-zone-set, pred-kind, pred-motion, why-links, sensor-blind, no-data,
alert-banner, alert-zone, checkin-toast, narrator-text, narrator-source, advice-text, before-dbm, after-dbm,
router-spot, train-button, train-seconds, zone-score, person-object-score, ms-per-decision, watts, bytes-out,
models-count, hide-tally
3D mirror (web/src/room): xray (data-max-db, data-max-xy) and beam-<link id> (data-drop-db, data-status, data-why),
  inside a visually hidden <ul data-testid="beams">.
Arrival: "Found you." is shown once pred has been present for 1.5 s, then held 3 s. Someone walking past the desk
  does not get it.
While armed: a passed_by is shown small and calm ("Someone passed by"), never in the fault colour. The intrusion
  alert is the only armed message in the fault colour.
Proof tiles (judge-facing screen): a tile with no measured value is not drawn at all. When no tile has one, the
  proof block and its divider are not drawn either. The test ids above stay in the page, hidden. A measured 0 is
  drawn. Nothing on any screen shows a number that is not measured.
Hall paths: "movement on this path" when moving, "path busy" when busy, "not calibrated" for a link with no
  empty_quiet_db in nodes.json. Never "clear".
```

## 9. Entry points (board/units/ start exactly these)
```
Board host: python -m bus | python -m radio.wifi_rssi | python -m radio.hci_scan --node unoq (root) |
            python -m teacher.camwatch | python -m brain.main |
            python -m store (the unit radio-sight-store, started after the brain) | python board/serve.py |
            python -m board.privacy (CAP_NET_ADMIN only, to read its counter) |
            python -m board.clock (root: it sets the clock and restarts the stack; as proposed, section 12) |
            llama-server (narrator/llm.service) | python -m narrator.narrate
Board App Lab: the camera teacher app (teacher/applab/), set as the default app. Nothing else runs in App Lab.
Pi A: python -m pi.radio_node --node pi5 (root) | the hotspot profile from pi/ap.sh
Pi B: python -m pi.radio_node --node pi5b (root) | WIFI_LINK=pi5>pi5b:wifi python -m radio.wifi_rssi |
      joined to the sensing hotspot, with BUS_HOST=192.168.77.2 for both programs. No hotspot, no Ethernet, no model.
Pi A and Pi B, optional: python -m pi.witness (the unit radio-sight-witness, section 13). With no key on the Pi it says
      "not enrolled" and ends; nothing else on the Pi waits on it.
Screen: a laptop's browser on the sensing hotspot (section 2). Nothing is started for it, and no Pi runs a kiosk.
Every folder that's run as a module has an __init__.py.
```

## 10. Ask the room, its history and its report (the board's web server)
```jsonc
POST http://192.168.77.2:8080/ask      {"question":"was anyone here in the last 10 minutes?"}
   // The body is at most 2048 bytes. The first 200 characters of the question are used.
200 {"answer":"Yes. Someone was here for 43 s of the last 10 minutes, most recently in Right from 18:21:49 to 18:22:09.",
     "rows":[{"row":"summary","seconds_with_someone":43},{"zone":2,"name":"Right","from":"18:21:49","to":"18:22:09","seconds":21}],
     "tool":"presence","args":{"minutes":10,"zone":null,"link":null},
     "picked_by":"llm","src":"sim","ms":5210,"span":{"from_t":1763149309000,"to_t":1763149329000}}
   // tool = presence | still_spans | alerts | intrusions | link_history | explain_advice | model_card, or null when the
   //   question fits none of them; then answer starts "I can answer: " and lists what can be asked, rows is [] and args is {}.
   // args = what the tool was run with: minutes (1-1440, 10 when the question names none), zone (a zone id in
   //   nodes.json, or null for anywhere) and link (a core link id, or null for any).
   // rows = the stored records the answer was filled from. Every number in answer is in a row, or is args.minutes.
   // picked_by = rules (keywords chose the tool: tried first, because they are right more often on plain questions) |
   // llm (no keyword matched, so the on-board model chose the tool). Either way the answer comes from the rows.
   //   The model only picks the tool and its args. It never writes the answer.
   // src = the src of the newest stored record (live | sim | replay), or null when nothing is stored.
   // ms = the whole time for the answer on the board.
   // span = optional: the stretch of time the answer is about (epoch ms), so the screen can offer a replay of it
   //   from /history. Missing when the answer is not about a stretch of time.
400 {"error":"..."} for a body that isn't {"question": non-empty string}; 503 when the agent isn't installed; 500 when it fails.
   // One question is answered at a time: llama-server has one slot, shared with the narrator.

GET http://192.168.77.2:8080/history?from_t=<epoch ms>&to_t=<epoch ms>
200 {"from_t":1763149300000,"to_t":1763149303000,"step_s":1,
     "rows":[{"t":1763149300000,"present":true,"zone":2,"zone_set":[2],"motion":"still","armed":true,"alert":false,
              "health":"ok","tamper":[]},
             {"t":1763149302000,"present":null,"zone":null,"zone_set":[],"motion":null,"armed":true,"alert":false,
              "health":"blind","tamper":["east"]}]}
   // The store is python -m store on the board (section 9). With it not running there are no records, so Ask,
   //   the replay and the report have nothing to answer from.
   // rows = what the store saved, one row for each second it saved, oldest first. A second with no saved row is
   //   simply missing: nothing is filled in or smoothed.
   // present:null = the brain did not know (blind, no model). It is never turned into false; zone and motion are then
   //   null and zone_set is []. present:false -> zone 0, zone_set [], motion null, as in pred.
   // alert = the no-movement alert was on (alert.state check_on). tamper = state.tamper in that second, [] when none.
   // At most 30 minutes per call: a longer stretch gets 400 {"error":"..."} with a plain message.

GET http://192.168.77.2:8080/report          // optional ?from_t=<epoch ms>&to_t=<epoch ms>; default = the last armed stretch
200 {"armed_from_t":1763149300000,"armed_to_t":null,
     "intrusions":[{"t":1763149312000,"zone":2},{"t":1763149340000,"link":"h>unoq:ble"}],
     "present_s":43,"passed_by":3,"tamper":[{"t":1763149350000,"node":"east"}],"blind_s":6,
     "text":"Armed at 18:21:40 and still armed. Intrusion alerts: 2. Someone was here for 43 s. ...",
     "rows":61,"ms":38}
   // armed_to_t is null while the space is still armed. An intrusion names a zone, or the hall link it was seen on
   //   (the same id as in the intrusion event). tamper lists each tamper event in the stretch.
   // passed_by = the number of passed_by events in the stretch (Armed, section 6). null only from a server that
   //   does not count them.
   // text = a short report in plain words. Every number in text equals a number in the other fields; the server
   //   checks this and uses a fixed template when it does not hold.
   // rows = how many stored records the report was built from. ms = the whole time for it on the board.
```

## 11. Privacy meter (GET /privacy on the board's web server)
```jsonc
// Polled about once a second. Always HTTP 200 and JSON, one of:
{"ok": true, "images": 0, "bytes_out": 0, "since_t": 1763149512200, "t": 1763149513200}
{"ok": false, "why": "privacy meter is not running"}
   // images: image or video files present now in the folders board/privacy.py lists (the project's data/, the
   //   App Lab apps folder, the teacher's mounted folders, and the files inside App Lab's running containers).
   // bytes_out: bytes the board and its containers sent since since_t to any address outside 192.168.77.0/24,
   //   10.42.0.0/24, loopback, link-local, multicast and broadcast (an nftables counter on postrouting). That is:
   //   bytes sent to the internet. What our own laptop and phone receive on our own network is not counted.
   // since_t: epoch ms when counting started. It changes only on an operator reset
   //   (python -m board.privacy reset, logged with the time) or a reboot. t: epoch ms of this reading.
   // ok is false when the meter isn't running, its last reading is more than 3 s old, or either number can't
   //   be read; then there are no numbers. Never a zero in place of an unknown. why is for the operator.
   // A network error or a 404 means the same as ok:false.
   // These are not proof.json's bytes_out and images_stored: those come from PROOF.md's own procedure
   //   (board/egress.sh over one measured run) and stay as measured.
```

## 12. Board clock (GET and POST /clock on the board's web server; as proposed in #632, not built yet)
```jsonc
// The closed network has no time source, so the board's clock is set from the operator's laptop.
// Both are answered only from the board itself, the cable and the sensing hotspot (403 otherwise). Always JSON.
// GET /clock: the board's time, and whether a step would be taken now.
{"t": 1763149512200, "busy": null, "last": null}
   // t: the board's epoch ms when it answered. The page's difference = its own clock - t (half the round trip is noise).
   // busy: null, or why POST would be refused right now, in plain words.
   // last: the last step the helper made since the board booted, or null:
   //   {"t": epoch ms after the step, "stepped_ms": n, "took_s": n, "ok": true} or {..., "ok": false, "why": "..."}
// POST /clock {"t": epoch ms}, the laptop's clock when it sends:
{"ok": true, "diff_ms": 520000, "stepping": true}    // 202: more than 2 s off; the clock is stepped and the stack restarts
{"ok": true, "diff_ms": 830, "stepping": false}      // 200: within 2 s; nothing happens
{"ok": false, "diff_ms": 520000, "why": "armed: disarm first"}   // 409: refused; nothing happens
{"ok": false, "why": "send {\"t\": epoch ms}"}       // 400 (bad body), 503 (the clock helper isn't running)
   // diff_ms = t - the board's clock when the request arrived; positive means the board is behind.
   // Refused while armed, while a recording is open (a lesson is one), while a fit is running, while a
   //   baseline is being captured, while the brain isn't answering, and while a step is already under way.
   // A step stops the bus, the readers, camwatch, the brain, the narrator and the privacy meter, sets
   //   the clock, and starts the ones that were running, in that order. The web server and the model server keep
   //   running. The screen's WebSocket drops for a few seconds and the page reconnects.
   // Operator only: the control is in the operator drawer, never on the judge-facing screen.
```

## 13. The sealed record, its witnesses and the detective (as worded in #866)
Everything here is optional on the wire: a part that knows none of it keeps working, and every older fixture stays valid.
```jsonc
// The sealed record (store, on the board). Every record the store saves, the once-a-second summary and every
// event, is also one link of a chain:
{"seq": 4127, "t": 1763149515000, "kind": "second", "body": {...}, "prev": "<64 hex>", "hash": "<64 hex>"}
   // seq: an integer from 1, no gaps. prev: the hash of the record before it (64 zeros for seq 1).
   // hash: SHA-256, in lower-case hex, of the canonical JSON of {seq, t, kind, body, prev}: keys sorted at every
   //   level, no spaces (separators "," and ":"), UTF-8, characters written as themselves (no \u escapes for
   //   non-ASCII), numbers as Python's json writes them. In Python:
   //   json.dumps({...}, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
   // kind and body:
   //   second          the summary of one second, as the store saved it (what /history is built from)
   //   <an event kind> {"id", "src", "info"} of that event (section 5)
   //   witness         {"node", "seq", "hash", "t", "sig"}: a signature that checked out, and the head it signs
   //   witness_bad     {"node", "seq", "why"}: a signature from an enrolled witness that did not check out
   //   witness_silent  {"node"}: that witness has not signed for 15 s (stored once)
   //   witness_back    {"node"}: it signed again (stored once)
   // A record is never rewritten. Order is seq, never t: the board's clock can be stepped (section 12).
   // Rows saved before the store sealed anything stay as they are, unsealed: the chain starts at the first record
   //   saved after that, with seq 1, and GET /chain counts the old rows in "unsealed".
   // Pruning drops the oldest records only, and keeps the seq and hash of the last one dropped as the anchor: the
   //   oldest kept record's prev is the anchor's hash. GET /chain says so in "anchor" and "first_seq".

// The board's web server. All three answer only on the board's own networks, like /history (403 otherwise).
GET http://192.168.77.2:8080/chain
200 {"head": {"seq": 4127, "hash": "<64 hex>", "t": 1763149515000}, "records": 4127, "since_t": 1763146000000,
     "verified": true, "last_verify_t": 1763149500000, "first_bad_seq": null,
     "witnesses": [{"node": "pi5", "last_seq": 4120, "last_t": 1763149510400, "sig_ok": true, "silent": false},
                   {"node": "pi5b", "last_seq": 4098, "last_t": 1763149490000, "sig_ok": true, "silent": true}],
     "first_seq": 1, "anchor": null, "unsealed": 0}
   // head: the newest record (seq 0 and 64 zeros while there is none). head.t is optional: the t of the last
   //   chain_head the board sent for this head, so a witness that reads the head here can sign it.
   // records: how many are kept. since_t: the t of the oldest kept record, null with none.
   // verified: true | false | "checking" (no check has finished yet). The board checks the last 10 minutes every
   //   30 s; last_verify_t is when the last check ended (null before the first), first_bad_seq the first record
   //   that failed (null when verified is not false).
   // witnesses: one entry for each enrolled witness, [] with none enrolled. last_seq and last_t (the board's clock
   //   when it checked the signature) are of its last good signature, null before the first. sig_ok: its newest
   //   signature checked out. silent: no good signature for 15 s.
   // first_seq, anchor ({"seq", "hash"} or null) and unsealed are optional. So are last_verify_checked (how many
   //   records the last 30 s check walked) and last_verify_ms (how long it took on the board), both null before
   //   the first check.

GET http://192.168.77.2:8080/chain/tail?n=40
200 {"records": [{"seq": 4120, "t": 1763149510000, "kind": "second", "hash": "<64 hex>", "prev": "<64 hex>"},
                 {"seq": 4121, "t": 1763149510400, "kind": "witness", "hash": "<64 hex>", "prev": "<64 hex>",
                  "node": "pi5", "for_seq": 4120}]}
   // The last n records (40 unless n says otherwise, at most 200), oldest first, without their bodies: cheap
   //   enough to ask for every second. node is there on a witness's records (witness, witness_bad,
   //   witness_silent, witness_back); for_seq, the record the signature vouches for, on a witness record only.

GET http://192.168.77.2:8080/chain/verify?from=<seq>&to=<seq>
200 {"ok": true, "checked": 3600, "first_bad_seq": null, "ms": 41, "from": 528, "to": 4127}
   // from and to are record numbers, both optional: without from it starts 3,600 records before to (or at the
   //   oldest kept record), without to it ends at the head. At most 100,000 records per call (400 otherwise).
   // A record is bad when its hash is not the hash of its own {seq, t, kind, body, prev}, when its prev is not the
   //   hash of the record before it, or when a seq is missing (then the missing seq is named).
   // checked: records read up to and including the bad one. ms: the time the check took on the board.
   // from and to (optional in the answer) are the range that was checked, null when no record is kept.

POST http://192.168.77.2:8080/chain/prove        // operator only; JSON; the body may be {} or {"n": 600, "seq": 3827}
200 {"ok": false, "altered_seq": 3827, "first_bad_seq": 3827, "ms": 9, "checked": 600, "kind": "second", "t": 1763149212000}
   // Copies the last n records (600 unless n says otherwise, at most 3,600) into memory, alters one record of
   //   the copy (seq, or one in the middle), checks the copy and names the record. It never writes to the real log.
   // checked, kind and t (of the altered record) are optional. 409 {"error": "..."} when there is no record yet.

// State (section 5) may carry the chain in short. Missing when the brain has heard no chain head for 15 s.
"chain": {"seq": 4127, "hash8": "1a2b3c4d", "verified": true, "witnesses_ok": 2, "witnesses": 2}
   // hash8: the first 8 hex of the head's hash. witnesses: how many are enrolled. witnesses_ok: how many of them
   //   are signing (not silent, last signature good).

// The witnesses (bus). Both messages carry the envelope of section 1, but their seq is the chain's record number,
// not a per-producer counter: the bus counts no gaps on them.
{"v":2,"type":"chain_head","t":1763149515000,"seq":4127,"src":"live","hash":"<64 hex>",
 "verified":true,"witnesses_ok":2,"witnesses":2}
   // From the board to the bus (127.0.0.1:5600) every 5 s. t: the board's clock when it was sent. verified,
   //   witnesses_ok and witnesses are optional: the brain copies them into state.chain.
   // The bus sends each chain_head on, from its own port, to every socket that sent it a chain_witness or a
   //   chain_sub in the last 60 s: a witness reads the head on the socket it sends from. A chain_sub
   //   ({"v":2,"type":"chain_sub","node":"pi5","src":"live"}) is only a witness saying it is there; it stops at
   //   the bus and is not a contract message. GET /chain carries the same head (head.seq, head.hash, head.t).
   // A witness signs a head whose seq steps back too (and notes it on its own device); it never signs seq 0.
{"v":2,"type":"chain_witness","t":1763149515000,"seq":4127,"src":"live","node":"pi5","hash":"<64 hex>","sig":"<base64>"}
   // From a witness to the bus (192.168.77.2:5600). seq, hash and t are the head it signs, exactly as given.
   // sig: the Ed25519 signature (64 bytes, in base64; hex is read too) over the ASCII bytes
   //   <node>|<seq>|<hash>|<t>      e.g.  pi5|4127|1a2b...f809|1763149515000      (no newline at the end)
   //   made with the openssl already on the device, from files (Ed25519 signs the message itself, so -rawin):
   //     openssl genpkey -algorithm ed25519 -out witness.key          # once, at install; never leaves the device
   //     openssl pkey -in witness.key -pubout -out witness.pub        # the public key, enrolled on the board
   //     openssl pkeyutl -sign -inkey witness.key -rawin -in msg.bin -out sig.bin
   //   and checked on the board with
   //     openssl pkeyutl -verify -pubin -inkey witness.pub -rawin -in msg.bin -sigfile sig.bin
   // Enrolment: data/witness_keys.local.json on the board (never in git), {"pi5": "<the PEM text of witness.pub>",
   //   "pi5b": "..."}. A missing file means no witnesses are enrolled; it is never an error. The web server reads
   //   the file again every second, so a key is enrolled without restarting anything.
   // The board stores a signature that checks out, for a record whose hash it holds, as a witness record; one that
   //   does not, from an enrolled node, as witness_bad (at most one every 5 s for each node). A message from a node
   //   that is not enrolled is dropped. A witness with no good signature for 15 s is stored once as witness_silent
   //   and, when it signs again, once as witness_back. The chain goes on either way.

// The detective (POST /ask, section 10). "What happened" questions are answered from sealed records only, and the
// answer may carry:
"steps": [{"tool": "records", "ms": 12, "rows": 61}, {"tool": "verify", "ms": 3, "rows": 61}], "cites": [4012, 4040], "chain_ok": true
   // tool is "story" for such an answer (one more value of tool in section 10).
   // steps: what was run, in order; ms may be a decimal. cites: the seq of each record the answer rests on.
   // chain_ok: the chain was verified over the cited range before answering. If it does not verify, the answer
   //   says so first and names the record. chain_ok is left out (never false) when the store holds no sealed
   //   record to check.
   // rows: one row for each sentence of the story, each with its own cites; span (section 10) covers the whole
   //   stretch, so the screen can offer a replay of it.

// The engine room (/engine/, a second screen, operator's): the three devices and their readings a second, the
// chain head ticking, signatures arriving from each witness, the last verify and its time, the models' timings and
// the prove-it check. Plain, dark, the same style rules, nothing under 20 px.
// Not in the demo: the camera and any microphone. Nothing about them is removed from the repo.
```
