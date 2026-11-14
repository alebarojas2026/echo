# Contracts (v2, frozen)

The message formats every part of Radio Sight agrees on. Only Ivan changes this file. Need a change? Open an issue labeled `contract`, keep working with what's here, and switch when the change lands.

Every adapter (fake feed, readers, bus, brain, screen) speaks exactly this.

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
- Board (UNO Q) hub Ethernet: 192.168.77.2/24. Pi eth0: 192.168.77.1/24. The Ethernet cable carries all
  traffic except sensing.
- Sensing Wi-Fi: the Pi's 5 GHz hotspot, 10.42.0.1/24. The board's wlan0 gets DHCP from it.
Ports:
- bus: UDP 0.0.0.0:5600 on the board. Senders:
  - processes on the board send to 127.0.0.1:5600;
  - the Pi sends to 192.168.77.2:5600;
  - the App Lab camera teacher sends to msgpack-rpc-router:5600 (App Lab's host alias; gate 3 confirms it).
- bus -> brain: UDP 127.0.0.1:5601.
- brain: WebSocket ws://192.168.77.2:8765/ws (bound to 127.0.0.1 and 192.168.77.2 only).
- web: http://192.168.77.2:8080. board/serve.py serves web/dist, /nodes.json and /proof.json.
- llm: http://127.0.0.1:8091 (llama-server).
```

## 3. Nodes, links, frame and zones (radio/nodes.json, served as /nodes.json)
```
Frame: metres. Origin = the square's south-west corner; x points east, y points north.
  The square is 2.0 x 2.0 m (if we shrink to 1.5 m, scale every coordinate).
Nodes, all 1.0 m high:
  unoq  N (1.0, 2.0, 1.0)  receiver
  pi5   S (1.0, 0.0, 1.0)  router + beacon + receiver
  east  E (2.0, 1.0, 1.0)  beacon
  west  W (0.0, 1.0, 1.0)  beacon
Link id = "<tx>><rx>:<kind>". Links: pi5>unoq:wifi, pi5>unoq:ble, east>unoq:ble, west>unoq:ble,
  east>pi5:ble, west>pi5:ble. Each link in nodes.json carries expected_hz, written after the baseline capture.
Zones: zone = 1 + (x >= 1) + 2*(y < 1); 0 = empty. 1 NW Bed, 2 NE Chair, 3 SW Hall, 4 SE Bathroom.
  zones: [{id, name, still_alert_s}] with 1 -> 60, 2 -> null, 3 -> null, 4 -> 10.
router_spots: S-home (1.0, 0.0, 1.0), S-W30 (0.7, 0.0, 1.0), S-E30 (1.3, 0.0, 1.0). Gate 7 sets the distance.
tray_spots: T1 (1.0, 0.2, 1.0).
Beacons are matched by manufacturer data FFFF 52 53 <'S' | 'E' | 'W'>, never by MAC.
```

## 4. Inputs to the bus
```jsonc
{"v":2,"type":"rssi","t":1763149512120,"seq":881,"src":"live","link":"east>pi5:ble","kind":"ble","tx":"east","rx":"pi5","dbm":-61}
{"v":2,"type":"label","t":1763149512150,"seq":412,"src":"live","frame":18231,"mode":"person","persons_in_frame":1,
 "present":true,"zone":4,"foot_m":[1.42,0.61],"motion":"moving","conf":0.81,"clipped":false}
   // One label per processed camera frame (5-10/s), including frames with nobody in them.
   // present:false only on a processed frame with no foot point inside the square.
   // clipped:true -> zone and foot_m are null and the window is dropped. mode = the current label_mode.
{"v":2,"type":"cam","t":1763149512200,"seq":77,"src":"live","state":"on","fps":9.6}
   // From teacher/camwatch.py: every 1 s and at once on any change. state = on | off | stalled.
{"v":2,"type":"narration","t":1763149513000,"seq":9,"src":"live","text":"Someone just walked into zone 2.",
 "event_id":"e123","event_kind":"enter","gen_ms":6120,"source":"llm","model":"<model name>"}
   // source = llm | template
{"v":2,"type":"meta","t":1763149500000,"seq":1,"src":"live","session":"s12","purpose":"heldout","walker":"w3"}
   // Sent on record_start. purpose = train | heldout | object | crowd | demo
```

## 5. Brain -> screen (WebSocket, about 10 state messages a second)
```jsonc
{"v":2,"type":"state","t":1763149512200,"seq":5012,"src":"live","cam":"on","router":"S-home",
 "links":[{"id":"east>pi5:ble","dbm":-63.0,"base_dbm":-58.1,"drop_db":4.9,"rate_hz":9.2,"expected_hz":9.5,"status":"ok","why":0.42}],
 "health":{"status":"ok","blind":[],"reason":null},                         // status ok|degraded|blind; reason rate|jump
 "pred":{"present":true,"kind":"person","zone":2,"zone_set":[2],"probs":[0.02,0.08,0.81,0.07,0.02],
         "motion":"still","still_s":4.2,"why":["east>unoq:ble","pi5>unoq:wifi"]},
        // probs = [empty, z1, z2, z3, z4]. kind = person | object | none.
        // pred is null before training, while health is blind, while recalibrating, and while the router is off S-home.
 "objects":[{"xy_m":[1.0,0.2],"near":"pi5","since_s":14.0,"drop_db":9.8}],
 "xray":{"w":10,"h":10,"cell_m":0.24,"origin_m":[-0.2,-0.2],"moving_db":[/* w*h */],"static_db":[/* w*h */],"n_links":6},
        // The screen draws whatever w x h it receives. Cells are row by row from the south edge:
        // index = iy*w + ix, ix east from origin_m[0], iy north from origin_m[1]; cell centre = origin_m + (i+0.5)*cell_m.
 "alert":{"state":"counting","zone":4,"still_s":7.2,"limit_s":10},          // none|counting|check_on
 "checkin":{"t":1763149511000,"link":"pi5>unoq:wifi"},                       // the last check-in, or null
 "advice":{"id":"a7","cause":"obstruction","near":"pi5","xy_m":[1.0,0.2],"link":"pi5>unoq:wifi","to_spot":"S-W30",
           "move_m":[-0.3,0.0],"dist_change_m":0.02,"text":"An obstruction next to the router is blocking its link to the receiver. Move the router 30 cm west.",
           "before_dbm":-71.2,"after_dbm":null,"why":["pi5>unoq:wifi","east>pi5:ble"]},   // or null
 "narration":{"text":"...","event_id":"e123","t":1763149513000,"source":"llm","gen_ms":6120},
 "teacher":{"present":true,"zone":3,"motion":"still"},                       // null when the camera is off
 "model":{"trained":true,"ver":"m3","train_s":8.4,"ms_per_decision":3.1,"windows":612,"train_sessions":["s07","s08"],"training":null},
 "board":{"cpu_temp_c":57.0,"cpu_mhz":2016,"cpu_pct":61}}
{"v":2,"type":"event","t":1763149512200,"seq":120,"src":"live","id":"e123","kind":"enter","info":{"zone":2}}
   // kinds: enter, exit, zone_change, checkin, object_on, object_off, advice, advice_result, router_moved, router_home,
   // recalibrating, cam_off, cam_on, cam_stalled, alert_on, alert_off, blind_on, blind_off, trained, baseline_done, drift.
   // info carries what the narrator needs: zone, link, node, before_dbm, after_dbm.
```
**Screen -> brain:**
```jsonc
{"v":2,"type":"cmd","cmd":"train|baseline|reset_alert|record_start|record_stop|label_mode|router_moved|router_home|relearn|truth","args":{}}
   // record_start {session, purpose, walker}; label_mode {mode: person|object|off}; router_moved {spot}; truth {zone} (crowd game).
```

## 6. Shared rules (every part computes the same thing)
```
Windows: 1.0 s long, 0.1 s hop, on recv_t. A window's label is the majority of the non-clipped camera labels in it.
  Windows with a clipped label or with no label are dropped from training.
Moving: foot speed > 0.25 m/s over 1 s, after a 0.5 s median filter.
Baseline: a 20 s capture with health ok, persons_in_frame == 0 from the camera, and label_mode off.
Link health:
- A link is stale when its rate over the last 2 s is < 0.4 x expected_hz.
- It is blind when stale for >= 3 s, or when pred.kind == none and |median - base| > 6 dB for >= 3 s.
- health is blind when any classifier link is blind. Then pred is null and the screen shows SENSOR BLIND (never "empty").
  Alert timers pause. It clears after 3 s ok.
Object (a training label): only in label_mode object. Every frame must have persons_in_frame == 0, and one or more
  links must drop >= 3 dB for >= 2 s with std < 0.8 dB.
Check-in (a rule, not learned): on pi5>unoq:wifi, >= 4 alternating crossings of +/-1.5 dB around the 1 s rolling median
  within 2.5 s, with pred.zone unchanged and no other link's drop changing by > 3 dB. Gate 8 tunes the thresholds.
Alert:
- still_s counts while kind == person, motion == still and the zone is unchanged.
- check_on when still_s >= zones[zone].still_alert_s. null never alerts, and objects never alert.
- It clears on a checkin or on reset_alert.
X-ray:
- The grid covers the square plus 0.2 m on each side.
- Weights per Wilson & Patwari: 1/sqrt(link length) inside an excess path <= 0.1 m.
- P = (W^T W + alpha I)^-1 W^T, computed at startup and again on router_moved and router_home.
- moving_db = last 1 s vs last 10 s. static_db = persistent change vs the baseline (>= 5 s, std < 0.8 dB).
- Static means "appeared since the baseline", never walls.
Advice:
- Fires when an object persists >= 5 s and its static_db peak lies within 0.5 m of pi5>unoq:wifi.
- Picks the router spot (not S-home) whose new link has the lowest summed static_db along its ellipse.
- The text is built from the result, never a fixed string.
- before_dbm = median of pi5>unoq:wifi over the 3 s before router_moved.
- after_dbm = median over 3 s, starting 2 s after router_moved.
Router: while the router is off S-home, pred is null. On router_home, every pi5 link must sit within 1 dB of base
  for 3 s; otherwise the board runs an automatic 20 s baseline ("recalibrating").
Narration:
- At most one sentence every 8 s. Only for an event <= 3 s old.
- At most 16 words. A banned word -> use the template sentence instead.
Screen: NO DATA (grey) when the last state is > 1 s old (the feed is stale). SENSOR BLIND when health is blind
  (the radio failed). These are different states.
```

## 7. proof.json (served as /proof.json)
```jsonc
{"zone":{"correct":47,"total":52,"ci95":[0.79,0.96],"sessions":["s21","s22"],"walkers":5,"method":"held-out, see PROOF.md"},
 "threshold_zone":{"correct":38,"total":52},
 "person_vs_object":{"correct":null,"total":null,"tray_placements":null},
 "false_alarms_per_min":null, "train_s":8.4, "ms_per_decision":{"p50":3.1,"p95":4.0},
 "watts":{"idle":null,"teaching":null,"radio_only":null,"source":null},
 "bytes_out":0, "images_stored":0, "models_on_board":3, "measured_at":"...", "commit":"..."}
   // A number not yet measured is null and shows as "__". Never invent one.
```

## 8. Screen test ids
```
source-badge, cam-status, pred-zone, pred-zone-set, pred-kind, pred-motion, why-links, sensor-blind, no-data,
alert-banner, alert-zone, checkin-toast, narrator-text, narrator-source, advice-text, before-dbm, after-dbm,
router-spot, train-button, train-seconds, zone-score, person-object-score, ms-per-decision, watts, bytes-out,
models-count, hide-tally
3D mirror (web/src/room): xray (data-max-db, data-max-xy) and beam-<link id> (data-drop-db, data-status, data-why),
  inside a visually hidden <ul data-testid="beams">.
```

## 9. Entry points (board/units/ start exactly these)
```
Board host: python -m bus | python -m radio.wifi_rssi | python -m radio.hci_scan --node unoq (root) |
            python -m teacher.camwatch | python -m brain.main | python board/serve.py |
            llama-server (narrator/llm.service) | python -m narrator.narrate
Board App Lab: the camera teacher app (teacher/applab/), set as the default app. Nothing else runs in App Lab.
Pi: python -m pi.radio_node (root) | the hotspot profile from pi/ap.sh | the kiosk command from board/kiosk-notes.md
Every folder that's run as a module has an __init__.py.
```
