# Radio Sight: Judge FAQ

## How does Radio Sight work?

Walk between two devices and the signal gives you away. Wi-Fi between the Pis is the main sensor; Bluetooth to the Arduino UNO Q gives a second opinion, and the board reports presence and movement in one spot.

## Isn't this just a threshold on signal strength?

A threshold can detect much of the empty-versus-present change. The local model learns signal patterns and movement from a camera's temporary labels; the camera is then unplugged.

## How can so few links locate someone?

We sense one spot across the gap between the desk and Pi B. This kit reports someone here, moving or still; it does not localize them to separate sides.

## Will it work on me?

Bodies and rooms differ, so the board learns the setup locally. You can give it a short lesson, then try moving and standing still after the camera is unplugged.

## What about two people, or someone walking behind me?

This demo is built around one person in the spot. An armed alert waits for sustained presence; multiple people and passers-by still need separate validation.

## Why these three devices?

The Arduino UNO Q and Pi A sit together on the desk; Pi B sits across the gap at desk height. They stand in for compatible radios and computing already in a building.

## Why not just use a camera?

A camera captures identifying visual detail. Ours supplies temporary setup labels, saves no image, and is unplugged before continued radio sensing.

## Why not a motion sensor?

Most Wi-Fi sensing only sees movement. Ours sees you standing still. Here, the Wi-Fi path across the gap provides presence evidence even when the person stops moving.

## Why not CSI or radar?

This board exposes signal strength, not CSI. Radar adds dedicated sensing hardware; our direction is to reuse compatible building radios.

## Can it identify people or count a crowd?

No, it reports presence and movement, not identity. Crowd counting is outside this prototype's validated scope.

## Does it work in any building?

It needs compatible radio readings and useful paths across the space. We have tested this desk arrangement; transfer to another room needs its own lesson and validation.

## What happens in a Wi-Fi dead spot?

The same Wi-Fi path across the gap shows a persistent blockage. The screen reports the weakened link, offers a configured router position, and shows a measured gain only when proof is available.

## Is the radio X-ray a picture?

No, it visualizes changes in measured radio links. It cannot reconstruct a face or camera-like detail, and one blocked path is not a complete building coverage map.

## Why run it on-device?

Training, inference, records, and answers stay on the board and our private network. The board has no internet connection on our demo network, so the live loop needs no cloud service.

## What runs on the Arduino UNO Q?

Training, inference, link health, alerts, advice, records, and local answers run on the Dragonwing CPU. The laptop and phone display the results through a browser on our network.

## What do the Pis do?

Pi A provides the private sensing hotspot and routes the laptop browser to the board over Ethernet. Pi B supplies the far endpoint across the gap; neither Raspberry Pi runs a model.

## Are you recording me?

The board saves local radio summaries and events for replay and answers. It stores no camera images, identifies nobody, and does not send those records to the internet.

## Isn't Wi-Fi sensing open to misuse?

Radio sensing can reveal presence, which deserves clear disclosure and limits. Our prototype processes locally, records no pictures or identity, and keeps its display and records on our own network.

## What about spoofing or jamming?

A silent device while armed can raise a tamper alert, but that does not diagnose jamming. We do not claim defenses against spoofed radio data or deliberate interference.

## What breaks first?

People outside the spot and radio interference can disturb the signal. A required link going blind produces Sensor blind, and stale data produces No data; neither means empty.

## What if the board dies?

The screen and phone say No data when the feed goes stale. The board is a single point of failure; a building deployment would need independent health monitoring.

## How does it scale?

The direction is local processing per space using compatible radios already there. We have tested one desk arrangement, not a building deployment.

## What does it cost?

This prototype uses an Arduino UNO Q and two Raspberry Pis, plus a temporary teaching camera. We have not established a deployment price; the product direction is software on compatible existing hardware.

## What did you write, and what is a library?

We wrote the radio pipeline, contracts, features, alert rules, records, local tools, and interface. We use scikit-learn, NumPy, OpenCV, three.js, Arduino App Bricks, and other credited libraries; the full list is in our credits.

## How does it fit Let's Dig In?

We dig into radio changes that a normal connection indicator hides. The same signal reveals presence and a blocked Wi-Fi path.

## Would you keep building it?

Yes: the next work is repeatable tests across people, interference, and room layouts. Broader deployment should follow that evidence, with clear privacy and failure behavior.

## How accurate is it?

The live signal response is measured, but that is not a held-out accuracy result. We report accuracy only with its method, sample size, date, and commit in the proof record.

## What is the no-movement alert?

It prompts a check when someone remains present and still; it does not diagnose why. The check-in is to lean aside, and a blind required link pauses the timer.

## What if someone unplugs it or blocks it?

While the space is armed, a device that goes silent raises a tamper alert that names the device, and the screen never says all clear while one is listed. A blocked or failed radio link makes the sensor say it is blind, which is not the same as empty. Neither case is hidden as a quiet room.

## What does the replay show, and is anything recorded?

The board keeps what the radio decided, once a second: present or not, which side, moving or still, and any alert. The replay plays those records back, and a second with no record shows as no record, never as an empty room. No image, sound or identity is recorded, and the records stay on the board.

## What about people walking past?

A person who only walks through is shown as “Someone passed by” and raises no intrusion alert. A person who steps in and stays through the sustained-person wait raises one; the measured rate remains `__` until that proof row is complete. The long hall links only report movement on a path, never who or how many.

## How do you know it isn't scripted?

Wave your hand in the sensing area and the live signal line moves with you. Step in, step out, or stand on the other side, and the screen follows what you do, not a timeline. Unplugging the camera or a beacon in front of you changes the screen the same way.

## What can Radio Sight not do yet?

It cannot identify people, count a crowd, or reconstruct camera-like detail. Accuracy across new rooms, multiple people, unfamiliar objects, and interference still needs measured validation.
