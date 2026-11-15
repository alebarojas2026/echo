# Echo: Wi-Fi that understands the room

**Taught by a camera. Runs without one.**

## Inspiration

Some places need to know someone is present without keeping a camera on them: patient rooms, bathrooms, study rooms and offices after hours. We wanted safety and after-hours security using the Wi-Fi already there, with a clear privacy boundary and a useful answer when the connection itself is blocked.

We built Echo at MadHacks 2026 for the Qualcomm / N+1 track and the theme “Let's Dig In.” We dug into the signal changes that an ordinary connection indicator hides.

## What it does

Walk between two devices and the Wi-Fi signal gives you away. Echo reports presence and movement in one spot from the Wi-Fi path between Pi A and Pi B; Bluetooth to the Arduino UNO Q gives a second opinion.

Most Wi-Fi sensing only sees movement. Ours sees you standing still. A temporary camera teaches the local model, then is unplugged; the radio keeps supplying the presence evidence. The prototype aims to distinguish person-vs-object patterns and movement from stillness, without identifying anyone or counting a crowd.

The six-beat demonstration is:

- **Found you:** the live signal changes as the judge enters the spot.
- **Teach the room:** a temporary camera provides labels and the UNO Q learns locally.
- **Camera unplug:** the cable comes out, the teacher goes off, and radio sensing continues while the person moves and stands still.
- **Intrusion alert:** the judge returns to an armed spot and stays until a local event appears on the phone.
- **Dead zone:** with nobody present, an object blocks the cross-gap Wi-Fi path; clearing it or moving Pi B provides a before-and-after test.
- **Ask the room and Proof:** the board answers from its saved records, and every published result has a proof method.

The radio X-ray visualizes measured link changes. A no-movement alert prompts a check, and the “I'm okay” check-in is to lean aside and wait for confirmation. A tamper alert names a device that goes silent while armed; Replay shows recorded summaries, and Incident report summarizes an armed stretch from those same records. Missing history remains unknown.

### Privacy by design

The camera is a temporary teacher, not the continuing sensor. No camera image is saved, the system does not identify anyone, and the laptop and phone use our private network. The sensing loop, records, on-board narrator and room questions need no cloud service; nothing is sent to the internet during the local demo. Live privacy counts are published only after verification.

### Proof

Every measured result stays blank until the [proof record](https://github.com/alebarojas2026/echo/blob/main/PROOF.md) supplies its method, sample size, date and commit. A live demonstration does not substitute for held-out validation.

| Result | Measured value |
|---|---:|
| Presence accuracy | __ |
| Person versus object | __ |
| Still versus moving | __ |
| Time to train | __ |
| Decision latency | __ |
| Update latency | __ |
| No-movement alert latency | __ |
| Dead-zone improvement | __ |
| Images stored | __ |
| Bytes sent outside the local network | __ |

### Current boundary

This is one spot with three devices, not a measured building deployment. No unfinished beat will be staged as live: each must pass preflight on the deployed kit. We do not claim validated operation with multiple people, unfamiliar objects, radios hidden in bags or panels, or different room layouts.

## How we built it

The Arduino UNO Q, powered by Qualcomm Dragonwing, is the computing hub. The board forms windows of radio readings, checks link health, trains compact models and makes learned decisions entirely on device on its Dragonwing CPU. Local contract-v2 messages connect readers, camera labels, decisions, controls and events.

The Arduino UNO Q and Pi A sit together on the desk, with Pi B about a metre away at desk height on a chair. Our development boards stand in for access points and radios in a building: Pi A provides the hotspot and wired route to the board, and Pi B supplies the far endpoint across the gap. Neither Pi runs a model.

A laptop browser shows the local interface; Pi A routes it to the UNO Q over direct Ethernet. A small local database stores summaries and events for Ask the room, replay and reports, without images or identity. The language model can select relevant records or phrase their facts; it is not the source of those facts.

The dead-zone advisor uses the same cross-gap Wi-Fi path, only for an object decision with nobody there. Pi A stays beside the cabled hub: the gain in this kit comes from clearing the object or moving Pi B, not a large router move.

## Challenges

Radio readings change with people, furniture, interference and device placement. We had to keep still presence separate from movement, distinguish learned person and object patterns, and prevent missing data from becoming an empty-room claim.

The physical kit changed the design. The Wi-Fi path across the gap became the primary sensor, Bluetooth became supporting evidence, and the short path between the desk devices stopped being a useful sensing line. A layout file now defines which links cross the spot.

Coordinating learning, alerts, records and a local interface required one frozen message contract. Clock changes, dropped links and interrupted recordings also had to leave clear evidence instead of confident but unsupported answers.

## Accomplishments

We built the local pipeline from radio readings and temporary labels to presence, movement, alerts and recorded explanations on an Arduino UNO Q. The unplugged camera makes the teaching boundary visible, and the live trace lets a judge change the input.

We also built local replay, incident reports, a no-movement alert with lean-aside check-in, and an object-blockage demonstration on the same Wi-Fi path. We keep the distinction between implemented features, the deployed preflight and measured accuracy explicit.

## What we learned

A temporary camera can teach a radio model without becoming the deployed sensor. Keeping a person present while still requires a presence decision separate from movement, and a blocked path is not automatically a person or a dead zone.

We also learned that failure behavior is part of the product. Sensor blind, No data and unknown history are useful answers when the evidence is missing.

## What's next

We will record repeatable held-out trials with people absent from training, varied objects, passers-by and interference. Every result will carry its method and limits in the proof record.

After that, we want to test more room layouts and compatible building radios, including hidden placements and additional sensing paths. The desk line is one strand of that direction; broader coverage and reuse of existing infrastructure require evidence.

## Images

This is the capture and caption plan for the submission lead. Take every demo view from the live desk, never the simulated demo. Include no recognisable face and no camera frame, ever. Keep photos, clips, and the exported diagram outside the repository; commit only this plan and the Mermaid source. Hide proof tiles until real results are available.

| Demo order | Image to capture | Caption |
|---|---|---|
| 1. Cover | A hand holding the unplugged USB plug in front of the screen with its found figure; optionally use a short continuous unplug clip if Devpost accepts it | The Arduino UNO Q keeps sensing the spot after the teaching camera is unplugged. |
| 2. Found you | Arrival words over the live room view, with the source visible | The Arduino UNO Q detects someone entering the spot from the Wi-Fi path between Pi A and Pi B. |
| 3. The lesson | Camera teaching status and progress, never the camera's image | The Arduino UNO Q learns locally from temporary camera labels. |
| 4. After the unplug | Radio only status, disconnected cable, and the figure remaining present when the person stops | The Arduino UNO Q continues presence and movement sensing from radio alone. |
| 5. Armed | The live phone intrusion card beside the screen | The Arduino UNO Q raises a local intrusion event when someone stays in the armed spot. |
| 6. The dead zone | Blocked-link advice and the verified before-and-after gain, only after the object is cleared or Pi B is moved | The Arduino UNO Q measures the blocked Wi-Fi path and the result of clearing the object or moving Pi B. |
| 7. The hardware | Label the Arduino UNO Q and Pi A together on the desk; label Pi B across the gap at desk height | The Arduino UNO Q runs the models; Pi A provides the hotspot and cable route, and Pi B supplies the far radio endpoint. |
| 8. Architecture | Export the current Mermaid diagram once for Devpost, outside the repository | The Arduino UNO Q runs sensing, local records, Ask the room, replay, reports, and alerts without a cloud service. |

Use the [current architecture source](https://github.com/alebarojas2026/echo/blob/main/docs/architecture.md). The layout has one spot and three devices. Wi-Fi across the gap is the primary sensor and dead-zone link; Bluetooth to the board is a second opinion. The capture lead must verify that each caption matches the deployed build before uploading.


## Built with

- Arduino UNO Q and Qualcomm Dragonwing
- Python, NumPy, scikit-learn, OpenCV, and WebSockets
- JSON Schema and referencing
- Three.js, TypeScript, Vite, Vitest, and Playwright
- glTF Transform and meshoptimizer
- Arduino App Bricks

The complete versions, licenses, research, and project links are in the [credits](https://github.com/alebarojas2026/echo/blob/main/docs/credits.md).

## Team

- **Alexander:** hardware, radio links, board services, and bring-up
- **Izet:** on-board sensing model, router advisor, and proof
- **Ivan:** contracts, room display, HUD, and web shell
- **Alejandro:** simulation, setup teacher, narrator, docs, and demo story
