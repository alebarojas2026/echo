# Contracts (v2.1: the desk layout, frozen)

The message formats every part of Radio Sight agrees on. Only Ivan changes this file. Need a change? Open an issue labeled `contract`, keep working with what's here, and switch when the change lands.

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
  GET /privacy is the live privacy meter (section 11). GET and POST /clock set the board's clock from the
  operator's laptop (section 12; as proposed, not built yet).
  It also has /layout for the operator's align mode: GET gives {"room": {offset_m, yaw_deg, scale, cut_m} | null,
  "hall_beacons": [{node, xyz_m}]} (every hall beacon in nodes.json; xyz_m is [x, y, z] or null). POST takes the
  same shape with either key or both (a room is never null there), JSON only, and only from the board itself,
  192.168.77.0/24 or 10.42.0.0/24; it answers like GET. It is saved on the board (data/layout.local.json) and is
  for drawing only: /nodes.json carries the saved hall xyz_m, and nothing else changes.
- llm: http://127.0.0.1:8091 (llama-server).
Operator key (when the board has one; see section 6):
- The operator opens the page as http://192.168.77.2:8080/?src=ws#key=<the key> . The part after # never leaves the
  browser, so it is in no request and no server log. The page keeps it in memory for that tab only (not in
  localStorage) and removes it from the address bar. A page opened without it shows everything and sends nothing:
  no operator drawer, and the Arm button reads "Locked". The phone's pages send no cmd but the crowd game's truth.
- POST /layout and POST /clock take the same key in the header X-Operator-Key (403 without it when the board has
  a key).
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
Code takes ids, positions, links, zones and spots from nodes.json, not from constants of its own.
The positions above are the last ones measured and written into nodes.json, and they will change: after the first
  tests on the real kit the devices are being moved (the beacons and Pi B to the far side of where the person stands;
  the 5 GHz Wi-Fi link from Pi A to Pi B is the best sensor). This section is rewritten when the new spots are
  measured. Until then, and after, code must never assume the geometry in this example: not which link crosses the
  strip, not which node is nearest, not which side a beacon is on. Only what nodes.json says.
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
        // cam = on | off | stalled | unknown.
        // off = the camera watcher's own reading that no camera is connected (it reports once a second).
        // unknown = no cam message in the last 3 s, or none yet: the board can't say. The screen never shows
        // "0 cameras" or "Camera unplugged" for unknown; it says "Camera status unknown". A cam message (section 4)
        // is never unknown: that is the brain's word for a watcher it cannot hear.
 "links":[{"id":"east>pi5:ble","dbm":-63.0,"base_dbm":-58.1,"drop_db":4.9,"rate_hz":9.2,"expected_hz":9.5,"status":"ok","why":0.42}],
 "health":{"status":"ok","blind":[],"reason":null},                         // status ok|degraded|blind; reason rate|jump
 "pred":{"present":true,"kind":"person","zone":2,"zone_set":[2],"probs":[0.04,0.11,0.85],
         "motion":"still","still_s":4.2,"why":["east>unoq:ble","east>pi5b:ble"]},
        // probs = [empty, z1, z2]: one entry for empty, then one per zone in nodes.json. kind = person | object | none.
        // pred is null before training, while health is blind, while recalibrating, and while the router is off S-home.
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
 "narration":{"text":"...","event_id":"e123","t":1763149513000,"source":"llm","gen_ms":6120},
 "teacher":{"present":true,"zone":1,"motion":"still"},                       // null when the camera is off or unknown
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
 "locked":true,                                                             // optional: the board has an operator key, so a page
                                                                            // needs it to send commands; missing means false
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
   // cam_off is sent only on a real off reading from the camera watcher. There is no event for cam unknown.
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
   // Operator key. When the board has OPERATOR_KEY in its .env (typed there once by a person; never in the repo,
   // never served by any endpoint, never logged), every cmd except truth must carry "key": "<the key>":
   //   {"v":2,"type":"cmd","cmd":"arm","args":{"on":false},"key":"<the key>"}
   // A cmd with a missing or wrong key is ignored: nothing changes and no event is sent (the brain logs one line,
   // without the key). The comparison is constant-time. With no OPERATOR_KEY on the board every cmd is accepted.
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
  label_mode off alone, and the operator keeps the strip empty. cam unknown counts as off here.
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
Object (a training label): only in label_mode object. Every frame must have persons_in_frame == 0, and one or more
  links must drop >= 3 dB for >= 2 s with the std of their 0.5 s means < 0.8 dB.
Check-in (a rule, not learned): on pi5>unoq:wifi, >= 4 alternating crossings of +/-1.5 dB around the 1 s rolling median
  within 2.5 s, with pred.zone unchanged and no other link's drop changing by > 3 dB. Gate 8 tunes the thresholds.
Alert:
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
Operator key (optional; set by OPERATOR_KEY in the board's .env):
- With a key on the board, only a page opened with it can arm, disarm, reset, take a baseline, train, relearn,
  record or move the router. truth is the one cmd that needs no key (the crowd game's phones send it).
- A cmd without the right key changes nothing and sends no event. state.locked tells every page the board has one.
- What it stops: a device that joined our network sending commands. What it does not do: it is not encryption.
  The key crosses our own WPA2 network in clear text, and a spoofed beacon or a fake reading sent to the bus
  (UDP 5600) is not covered. Say so when asked.
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
Router: take the tray off and put Pi A back on S-home BEFORE sending router_home. While the router is off S-home, pred is null. On router_home, every pi5 link must sit within 1 dB of base
  for 3 s (a pi5 link has pi5 as its tx or rx: links 1, 2, 5, 6, 8, 9 and 12; pi5b is a different node); otherwise the board runs an automatic 20 s baseline ("recalibrating").
Narration:
- At most one narration every 8 s, a recap included: the sentence after a recap waits 8 s.
- Only for an event <= 3 s old.
- At most 16 words (a recap: at most 3 sentences and 45 words). A banned word -> use the template sentence instead.
Screen: NO DATA (grey) when the last state is > 1 s old (the feed is stale). SENSOR BLIND when health is blind
  (the radio failed). These are different states.
```

## 7. proof.json (served as /proof.json)
The values below show the format only; they are not results.
```jsonc
   // These values show the format only. They are not results.
{"zone":{"correct":47,"total":52,"ci95":[0.79,0.96],"sessions":["s21","s22"],"walkers":5,"method":"held-out, see PROOF.md",
         "majority_class_correct":null},
 "threshold_zone":{"correct":38,"total":52},
 "presence":{"correct":null,"total":null,"always_empty_correct":null,"cycles":null,"method":"held-out cycles, see PROOF.md"},
   // presence is optional. It is somebody there or nobody, scored per second on held-out empty and occupied cycles,
   // against a written enter/leave log or the camera. always_empty_correct = how many of the same seconds a model
   // that always says "nobody" would get right: shown beside the score, so a lopsided set can't flatter it.
   // cycles is null when the truth came from the camera (it cannot count cycles).
   // zone.majority_class_correct is optional: how many of zone.total a model that always names the commonest
   // zone would get right. Shown beside the zone score for the same reason.
 "person_vs_object":{"correct":null,"total":null,"tray_placements":null},
 "false_alarms_per_min":null, "train_s":8.4, "ms_per_decision":{"p50":3.1,"p95":4.0},
 "watts":{"idle":null,"teaching":null,"radio_only":null,"source":null},
 "bytes_out":0, "images_stored":0, "models_on_board":3, "measured_at":"...", "commit":"...",
   // bytes_out = bytes sent to the internet over the measured run. The privacy claim is "nothing is sent to the
   // internet", never "nothing leaves the board": our own laptop and phone, on our own network, receive the
   // screen's data.
 "security":{
   "detection":{"entries":null,"detected":null,"ci95":null,"armed_entries":null,"intrusions":null,"intrusion_ci95":null,"within_s":5,"hold_s":3},
   "false_alarms":{"presence_events":null,"intrusions":null,"duration_s":null,"armed_duration_s":null,
                   "presence_per_hour":null,"intrusions_per_hour":null,
                   "passed_by_events":null,"passed_by_duration_s":null,"passed_by_per_hour":null},
   "fewer_devices":[{"name":"...","nodes":["unoq","pi5"],"links":["pi5>unoq:wifi"],
                     "zone":{"correct":null,"total":null},"presence":{"entries":null,"detected":null,"ci95":null}}]}}
   // A number not yet measured is null. Never invent one. PROOF.md, the docs and the operator's view show it as "__".
   // The judge-facing screen leaves its tile out (section 8). A measured 0 is a number and is shown.
   // security is optional (the whole object may be missing). Every unmeasured value in it is null.
   // detection: entries are independently labeled empty -> present transitions; a trial counts only with continuous
   //   truth and captured predictions through the deadline (within_s). Intrusion trials also need captured armed coverage.
   //   within_s is the deadline for an armed intrusion: armed.hold_s + 2 (5 by default). hold_s (optional) records
   //   the hold that was set. A camera entry shorter than hold_s is not an armed-entry miss; it is still a presence
   //   trial. Presence is always judged within 2 s, and the table says so.
   // false_alarms: passed_by_events, passed_by_duration_s and passed_by_per_hour (optional) count passed_by events
   //   over all continuously captured armed time, blind states included. They count events, not people. A passed_by
   //   is never an intrusion or a false intrusion, and an intrusion matched within the deadline is not a false one
   //   after the person has left.
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
models-count, hide-tally, presence-score
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
   // picked_by = llm (the on-board model chose the tool) | rules (the model was down or slow; keywords chose it).
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
