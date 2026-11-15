# Echo: Twenty Hard Judge Questions

Each answer is two sentences. Speak the answer; offer the records or the proof page when asked. It can't see you, it can't be edited, and it still tells you exactly what happened.

## Isn't this just a laser tripwire?

A tripwire says something crossed; Echo says someone arrived, stayed still or moved, and left, then seals that record. It also found a person with Pi B hidden in a backpack, which a light beam cannot do.

## Isn't presence just a signal-strength threshold?

Yes, and we say so: after a baseline with the spot empty, a Wi-Fi drop that holds is a person. The work is in keeping it steady, sealing every record and answering from it.

## How does the real kit work?

Pi A makes a Wi-Fi signal and Pi B, a metre away at desk height, measures it many times a second. The Arduino UNO Q compares that with the empty spot and decides locally.

## Does standing still make me disappear?

No, because presence comes from your body weakening the line, not from movement. Still or moving is a separate word, and it takes a few seconds to change.

## Will it work on me or in another room?

It needs no training on you: one baseline with the spot empty is the whole setup. Our measurements are one person on one night, so other people and rooms still need testing.

## What about two people or someone passing behind me?

Echo senses one spot and does not count people. Someone to the side or behind the device was only seen during tuning, so we give no result for it.

## What breaks it?

A walk straight through is not reliably seen, because a person needs a few seconds on the line. It senses one spot only, and Pi B must sit at about desk height.

## Why not CSI, radar or a motion sensor?

This board exposes signal strength, not CSI, and radar needs its own hardware. A motion sensor forgets you when you stop moving, and none of them keeps a sealed record.

## Why is there no camera at all?

The places this is for cannot have one, so Echo never uses one. There is no camera and no microphone on the kit.

## Are you recording me?

The board records that someone was on the spot, when, and still or moving, with nothing that says who. It holds no pictures and no sound.

## What exactly runs on the chip?

The decision, the alerts, the sealed record, the signature checks, the language model and the web pages all run on the Arduino UNO Q's Qualcomm Dragonwing CPU. Neither Pi runs a model, and Echo calls no cloud service.

## How do I know the record was not edited?

Each record carries the hash of the one before, so one change breaks every seal after it. Prove it changes a copy and the board names the altered record.

## What stops the board from rewriting the whole record?

Each Pi signs the newest record every five seconds with a key that never leaves that Pi. Rewriting history would mean forging both signatures as well.

## Can I spoof it, jam it or unplug it?

Unplug a device and Echo says which one went quiet and records the gap. We do not claim a defence against spoofed radio or deliberate jamming.

## What happens when the board or a link fails?

If the Wi-Fi line stops reporting the screen says the sensor is blind, and a stale feed says no data. Neither means empty, and the board remains a single point of failure.

## How accurate is it, and how do I know it isn't scripted?

One person stood on the spot for ten seconds, ten times, and Echo found them 10 of 10 times; with this few trials the true rate is probably between 69% and 100%. Step in yourself, then open the records.

## Can the language model invent what happened?

It answers from sealed records only and shows its steps and the records it used. If its wording is doubtful, open those records; the facts are there.

## What is the no-movement alert and how do I answer it?

It prompts a check when someone stays present and still; it does not say why. Step aside and back to say you're okay, and wait for the confirmation.

## What does it cost and how would it scale?

This prototype is an Arduino UNO Q and two Raspberry Pis; we have no deployment price. The idea is to use an access point and a device a building already has, which is untested.

## How does this fit Let's Dig In, and would you continue?

We dug into a signal every building already has and found a witness in it. We would keep building it, starting with more people, more rooms and live measurements.
