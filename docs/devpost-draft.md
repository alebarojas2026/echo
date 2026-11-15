# Radio Sight: Safety and After-Hours Security with Wi-Fi

**Wi-Fi that understands the room.**

## Inspiration

Radio Sight brings safety and after-hours security to buildings using the Wi-Fi already there, with no permanent camera and no cloud dependency.

Patient rooms, bathrooms, study rooms, and offices after hours all need a simple answer to the same question: is someone present, and are they moving? A camera often captures far more than that question requires. We wanted the radio links already crossing a room to provide a smaller, private signal that can be understood locally.

We built Radio Sight at MadHacks twenty twenty-six for the Qualcomm / N+1 track and the theme “Let’s Dig In.” We dug into the way people and objects reshape radio paths and turned those changes into a room-aware local system.

## What it does

Radio Sight reads changes across Wi-Fi and Bluetooth links around a sensing area. A model on the Arduino UNO Q reports presence, movement, zone, and whether a learned pattern looks like a person or object. It does not identify anyone or count a crowd.

### Who it is for

- patient rooms where staff need a private presence or no-movement prompt;
- bathrooms where a permanent camera does not belong;
- study rooms that should show occupancy without tracking a visitor's phone; and
- offices after hours where a new person pattern should create a local intrusion alert.

### What's new

A temporary camera teaches the radio model on the board. It supplies zone and motion labels for a short room lesson, saves no image, and is then unplugged. Training and live inference run on the UNO Q's Dragonwing CPU, while the Raspberry Pi provides network and radio and runs no model.

The primary story uses the same eight beats as our runbook:

- **Found you:** the changed radio links report that a person entered.
- **Teach the room:** the temporary camera labels a fresh local lesson.
- **Camera unplug:** the teacher goes off and stays off.
- **Still follows:** radio continues reporting presence when the person moves or stands still.
- **Arm the space:** armed mode says the room should be empty.
- **Intrusion alert:** a new sustained person appearance creates one local event and phone-page alert.
- **Ask the room:** a question is answered from timestamped local records.
- **Proof:** every public measurement comes from the proof record; missing results stay `__`.

The measured zone accuracy is __ ([method](../PROOF.md)). The measured presence accuracy is __ ([method](../PROOF.md)). The measured person-vs-object accuracy is __ ([method](../PROOF.md)). The measured update latency is __ ([method](../PROOF.md)). The measured no-movement alert latency is __ ([method](../PROOF.md)). The measured dead-zone improvement is __ ([method](../PROOF.md)). Images stored is __ and bytes sent outside the local network is __ until those proof rows are complete.

### How it is different

Commercial Wi-Fi products make different architecture choices, so we do not claim they all work the same way. [Aerial documents hybrid cloud and edge deployment](https://aerial.ai/motion-intelligence), while [Origin documents edge sensing that can communicate activity events to cloud services](https://www.originwirelessai.com/trupresence-2/). Radio Sight's training, inference, event decisions, and demo display stay on the UNO Q and its private local network; it requires no vendor cloud for the live loop.

Building location analytics can also answer a different question. [Cisco Meraki describes detecting Wi-Fi and Bluetooth client devices and aggregating their location data in the Meraki cloud](https://documentation.meraki.com/Wireless/Operate_and_Maintain/User_Guides/Monitoring_and_Reporting/Location_Analytics). Radio Sight instead measures how a person changes the room's radio links, so the person does not need to carry the device being located.

The radio X-ray, person-vs-object result, no-movement alert, check-in, dead-zone advisor, and on-board narrator remain available for the finalist round and judge questions rather than crowding the primary desk story.

## How we built it

The Arduino UNO Q is the computing hub. Versioned local messages bring in radio signal measurements, temporary teacher labels, link health, commands, and events. The board forms time windows, rejects unusable inputs, trains a compact model, and makes learned decisions on the Dragonwing CPU.

The setup camera sends labels, not saved images. After a successful lesson, the camera is then unplugged. A blind required link produces no prediction rather than an empty-room claim, and unmeasured proof values render as `__`.

Our development boards stand in for access points and radios that are already distributed through a building. The Pi supplies the private hotspot and one radio path; the UNO Q and beacon nodes supply the other measured paths. A production deployment would integrate with compatible building radios instead of placing this exact set of boards in every room.

A laptop browser shows the local interface over the Pi's private hotspot. The Pi routes it to the UNO Q over direct Ethernet. The web interface presents the live room, changed links, predictions, armed state, alerts, event records, narration, and proof without sending the sensing loop to a cloud service.

## Challenges

Radio data is noisy. Doors, furniture, interference, transmission bursts, and small body turns can all change a link. We had to distinguish a person from an object, keep stillness from looking like absence, and keep a failed radio link from becoming a false all-clear.

The model also belongs to its room. Node placement, layout, and materials change the paths, so setup needs a clean baseline and a short labeled lesson. Presence may transfer as a product capability, but detailed zone and motion behavior must be taught and tested in each deployment.

The complete hero path crosses radio collection, teaching, training, live inference, armed mode, the phone page, event storage, room questions, and proof. Keeping one frozen contract across those pieces was as important as any individual model.

## Accomplishments

We built a private local loop that learns radio patterns, keeps sensing after the camera is disconnected, reports presence and movement, separates learned person and object patterns, and refuses to guess when required links are blind. The radio X-ray connects each decision to changed links rather than presenting a label with no explanation.

We also built the no-movement alert, deliberate check-in, caregiver phone page, dead-zone advisor, on-board narrator, and a fact-based end-of-demo recap. The primary story now gives each feature a clear place instead of trying to show everything at once.

Privacy and proof are part of the architecture. The camera is temporary, images are not saved, learned work runs on the UNO Q, and every incomplete measurement stays `__` rather than becoming a demo estimate.

One honest line about what does not work yet: the complete armed phone-alert and room-question path is still being integrated into `main`, and no unfinished beat will be staged as live.

## What we learned

A camera can be useful as a temporary teacher without becoming the deployed sensor. The important boundary is visible: teach, verify the model, unplug, and continue from radio alone.

Building radio analytics and device location are not the same thing. Measuring the room's links can report a person's effect without asking that person to install an app or carry a tracked device.

We also learned that missing-data behavior is part of the product. “Sensor blind” is safer and more honest than “empty,” and a blank proof value is better than an impressive number with no method.

## What's next

First, we will finish and test the armed phone-alert and local room-question integrations, then run the complete hero path without fallbacks. We will also test the caregiver page on a real phone and record every proof result with its method, sample size, date, and commit.

After the hackathon, we want to test more building layouts, materials, access-point arrangements, and groups of people. We will measure how much of the local model can transfer between rooms, expand held-out proof, and develop the current blocked-link view into a full coverage map.

## Built with

- Arduino UNO Q and Qualcomm Dragonwing
- Python, NumPy, scikit-learn, OpenCV, and WebSockets
- JSON Schema and referencing
- Three.js, TypeScript, Vite, Vitest, and Playwright
- glTF Transform and meshoptimizer
- Arduino App Bricks

The complete versions, licenses, research, and project links are in [credits.md](credits.md).

## Team

- **Alexander:** hardware, radio links, board services, and bring-up
- **Izet:** on-board sensing model, router advisor, and proof
- **Ivan:** contracts, room display, HUD, and web shell
- **Alejandro:** simulation, setup teacher, narrator, docs, and demo story
