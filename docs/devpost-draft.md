# Radio Sight

**Wi-Fi that understands the room.**

## Inspiration

Wi-Fi problems are usually described with a single signal-strength number, but rooms are not simple. Walls, furniture, people, and device placement all change how radio signals travel. A connection can look healthy near the router while failing exactly where someone needs it.

We wanted to dig into those invisible changes and make them useful. Radio Sight turns the Wi-Fi signals already crossing a room into a private, local picture of coverage, presence, and movement. It gives people a direct way to understand why a space behaves the way it does without adding a permanent camera or sending data to the cloud.

We built Radio Sight at MadHacks 2026 for the Qualcomm / N+1 track and its theme, "Let's Dig In."

## What it does

Radio Sight reads how people and objects change the radio links in a room. It combines those changes into a live radio map that can:

- find real dead zones instead of guessing from a router's advertised range;
- distinguish stationary obstructions from moving people;
- report whether someone is present and moving;
- raise a no-movement alert when the radio pattern remains still for the configured period; and
- explain what changed in plain language.

During setup, an attached camera provides temporary location labels so the on-board model can learn the room's radio patterns. The camera is then unplugged. No image is saved, and live operation uses radio data alone. Processing stays on the Arduino UNO Q, powered by Qualcomm Dragonwing, so room data does not need to leave the device.

Our measured localization accuracy is __. Our measured end-to-end update latency is __. Full methods and limits belong with those results so the demo stays honest.

## How we built it

We placed small radio nodes around a floor zone: the Arduino UNO Q, a Raspberry Pi 5 acting as the router, and beacon nodes. Each node measures signal strength across the available links. A message contract keeps the radio readers, training pipeline, room display, advisor, and proof tools in sync.

The setup pipeline uses camera labels only as a temporary teacher. A small model trains on the UNO Q to associate link changes with locations. After setup, the camera is disconnected and the model predicts from radio measurements alone.

The board combines the link measurements into a radio image of the room. Stable changes point to obstructions or persistent coverage problems; changing patterns point to human movement. A local web interface shows the room, radio links, dead zones, presence and movement status, and plain-language explanations. A placement advisor then suggests how to move equipment and verifies whether the change improved coverage.

Everything runs locally. The system does not require a cloud service for inference, storage, or the live display.

## Challenges

Radio data is noisy. Signal strength changes when a door moves, a chair shifts, another device transmits, or a person turns in place. We had to separate useful structure from ordinary variation without pretending the signal was cleaner than it was.

The room also matters. A model trained against one layout cannot assume that every other space has the same radio paths. We designed setup as an explicit calibration step and kept the product focused on explaining the current room.

Integrating the full path was another challenge: radio collection, temporary camera labels, on-board learning, live predictions, the room display, advice, and proof all had to agree on timing and message formats. Running the pipeline on the Arduino UNO Q forced us to keep each part small and deliberate.

## Accomplishments

We built a complete local loop from measurement to action. Radio Sight collects real link data, learns a room, runs without the setup camera, identifies dead zones, tracks presence and movement, explains its output, recommends a placement change, and measures the result after the change.

We are especially proud that privacy is part of the architecture, not a promise added at the end. Camera input is temporary, images are never saved, and the live system works with the camera unplugged. The Qualcomm Dragonwing platform gives us enough on-device capability to keep the experience responsive without a cloud dependency.

We also built proof into the project. The measured dead-zone improvement is __. The measured presence accuracy is __. The measured no-movement alert latency is __.

## What we learned

The strongest demo is not a visualization alone; it is a before-and-after result. Finding a weak area matters, but showing that a placement change improves the measured links makes the system useful.

We learned that temporary camera supervision can teach a radio model without making the camera part of the final product. We also learned to treat calibration, uncertainty, and honest limits as product features. Radio sensing is most credible when the interface explains what the system knows, what changed, and what still needs verification.

Finally, shared contracts mattered as much as the model. A clear message format let the hardware, learning, interface, advisor, and measurement work advance independently and then connect.

## What's next

Next, we want to test Radio Sight across more room shapes, materials, furniture layouts, and radio environments. We will strengthen the calibration flow, quantify uncertainty, and expand the proof report with repeatable methods for localization, latency, and coverage improvement.

We also want the placement advisor to compare more candidate changes and make the reasoning behind each recommendation clearer. Longer term, Radio Sight could become a practical local tool for Wi-Fi setup, room-aware interfaces, and privacy-preserving occupancy features on edge hardware.
