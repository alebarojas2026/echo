# Radio Sight

**Wi-Fi that understands the room.**

## Inspiration

Wi-Fi problems are usually reduced to one signal-strength bar, but rooms are not simple. Furniture, people, walls, and router placement reshape every radio path. A connection can look healthy beside the router while failing exactly where someone needs it.

We wanted to dig into those invisible changes and make them useful. Radio Sight turns the radio links already crossing a room into a private, local picture of coverage, presence, and movement. It explains what changed without a permanent camera or a cloud connection.

We built Radio Sight at MadHacks twenty twenty-six for the Qualcomm / N+1 track and the theme “Let’s Dig In.”

## What it does

Radio Sight reads how people and objects change Wi-Fi and Bluetooth links around a room. It combines those changes into a live radio X-ray and a dark three-dimensional room display that can:

- find a real dead zone and show the links behind it;
- report presence, movement, and the predicted zone;
- make a person-vs-object decision without identifying the person;
- keep persistent object change separate from fresh human activity;
- raise a no-movement alert after the configured still period;
- mirror that alert on a caregiver phone page, chime once, and return to calm after a check-in;
- recognize a deliberate wave check-in without a phone or button;
- use a dead-zone advisor to recommend a router position and compare the link before and after the move; and
- use an on-board narrator to explain fresh events and recap the demo in plain language.

During setup, a camera provides temporary zone and motion labels. The model trains locally on the Arduino UNO Q, and the camera is then unplugged. No image is saved. Live inference uses radio alone, all learned decisions run on the Dragonwing CPU, and the Raspberry Pi runs no model.

Our measured zone accuracy is __ ([method](../PROOF.md)). Our measured presence accuracy is __ ([method](../PROOF.md)). Our measured person-vs-object accuracy is __ ([method](../PROOF.md)). Our measured end-to-end update latency is __ ([method](../PROOF.md)). Our measured dead-zone improvement is __ ([method](../PROOF.md)). Our measured no-movement alert latency is __ ([method](../PROOF.md)).

The demo tells one story:

- **Judge walks in:** the radio state changes and the room reports a moving person and zone.
- **Radio X-ray:** the display connects the prediction to the radio links behind it.
- **No-movement alert:** the local still timer reaches the configured limit in an enabled zone.
- **Wave check-in:** a practiced radio motion clears the alert without a phone or button.
- **Tray vs person:** a metal tray becomes a stable object pattern, not a person.
- **Router advice:** the advisor names a tested router position and preserves before-and-after readings.
- **Camera unplug:** the setup teacher goes off while the live radio state keeps updating.
- **Proof:** every missing measurement remains `__` instead of becoming an estimate.

## How we built it

Radio nodes sit around a marked floor square: the Arduino UNO Q at one side, a Raspberry Pi acting as the router and a radio node, and beacon nodes on the other sides. The readers send signal-strength measurements into a versioned local message bus. The board joins them into time windows, checks link health, and feeds the trained person, object, zone, and motion model.

The setup camera acts only as a teacher. It sends labels rather than saved images. Clipped or unlabeled windows are rejected, and training and inference run on the UNO Q. After training, the camera can be unplugged while the radio pipeline, room display, alert logic, advisor, and narrator continue.

The radio X-ray separates persistent change since the room baseline from the fresh change associated with a person. A steady tray pattern can become an object and trigger placement advice near the router. Removing that object lets the static state come back down instead of leaving a ghost obstruction.

The web interface shows the dark three-dimensional room, link health, the radio X-ray, predictions, alerts, advice, narration, and proof values. A laptop browser shows that interface over the private hotspot, while the Raspberry Pi routes it to the board over the direct Ethernet cable. The Pi does not train or run a model, and the demo does not depend on venue Wi-Fi.

## Challenges

Radio data is noisy. A door, chair, transmission burst, or small body turn can alter a link. We had to keep brief variation from resetting the no-movement timer, keep a steady object from looking like a failed sensor, and keep a broken link from looking like an empty room.

The room also matters. A model trained in one layout cannot assume another room has the same paths. We made calibration explicit: mark the layout, calibrate the temporary teacher, capture an empty baseline, record training sessions, and repeat those steps in the presentation room.

The full path had to agree on one contract: radio collection, temporary camera labels, training, live predictions, check-ins, alerts, the room display, narration, advice, and proof. Running the learned work on the UNO Q forced us to keep every stage focused and observable.

## Accomplishments

We built a complete local loop from signal change to action. Radio Sight learns a room, runs after the camera is unplugged, distinguishes person and object patterns, tracks presence and movement, recognizes a check-in, raises a no-movement alert, explains events with an on-board narrator, recommends a placement change, records the result of that move, and produces a short end-of-demo recap from the run's real events.

We also built a caregiver phone page that chimes once when the no-movement alert fires and returns to calm after a check-in. Its real-phone audio and layout check still remains.

Privacy is part of the architecture. The camera is temporary, images are never saved, live sensing is radio-only, and no cloud service is required for the model or display. When data is stale or a classifier link is blind, the system says so and pauses its prediction instead of claiming the room is empty.

We also built honest proof into the interface. Unmeasured results stay `__`, simulation never becomes a public result, and each final claim points back to the method in [PROOF.md](../PROOF.md).

## What we learned

The strongest demo is a before-and-after result, not a visualization alone. Finding a weak area is useful; showing why it is weak, recommending a change, and measuring the same link again makes the system actionable.

Temporary camera supervision can teach a radio model without making the camera part of the product. We also learned that calibration, link health, missing-data states, and honest limits deserve the same design attention as the model.

Shared contracts mattered as much as any individual algorithm. They let the radio, model, interface, advisor, narrator, and proof work advance independently and still connect into one room-aware experience.

## What's next

Next, we will run the caregiver page on a real phone to check its chime and layout in the presentation setup.

After the hackathon, we want to test more room shapes, materials, furniture layouts, and radio environments. We will expand held-out proof, strengthen calibration, quantify uncertainty, and compare more candidate router placements.

## Built with

- Arduino UNO Q and Qualcomm Dragonwing
- Python, NumPy, scikit-learn, OpenCV, and WebSockets
- JSON Schema and referencing
- Three.js, TypeScript, Vite, Vitest, and Playwright
- glTF Transform and meshoptimizer
- Arduino App Bricks

The complete versions, licenses, and project links are in [credits.md](credits.md).

## Team

- **Alexander:** hardware, radio links, board services, and bring-up
- **Izet:** on-board sensing model, router advisor, and proof
- **Ivan:** contracts, dark room display, HUD, and web shell
- **Alejandro:** simulation, setup teacher, narrator, docs, and demo story
