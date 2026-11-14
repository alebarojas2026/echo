# Proof

Every number shown on screen or in the pitch has a row here: what was measured, how, on how many people or sessions, when, and on which commit.

| Number | Value | Method | N | Date | Commit |
|---|---|---|---|---|---|
| Zone accuracy (radio vs camera agreement; the "localization accuracy" in the Devpost draft) | pending | Held-out sessions with the camera still recording but the model predicting from radio only. Compare predicted zone to camera zone at each timestamp. Report % agreement, confusion matrix, and chance baseline (1 ÷ number of zones). | 3+ people, 5+ held-out sessions | | |
| Presence accuracy | pending | Scripted cycles: 2 min empty room, 2 min occupied. Ground truth from the camera or a written enter/leave log. Report accuracy and false alarms while empty. | 10+ empty/occupied cycles | | |
| Person vs object accuracy | pending | Place a still object (box, chair, water jug) in the zone, then a person. Count how often each is labeled obstruction vs person. | 10+ trials each | | |
| Time to train on the board | pending | Wall-clock time on the UNO Q from training start to model ready. Report the median. | 3+ runs | | |
| Time per decision | pending | Time around the prediction step on the board. Report median and 95th percentile. | 1,000+ predictions | | |
| End-to-end update latency | pending | Slow-motion phone video with the person and the screen in one shot. Count frames from the step into the zone to the screen changing. | 10+ trials | | |
| No-movement alert latency | pending | Same video method: time from the person freezing to the alert, minus the configured wait period. | 5+ trials | | |
| Dead-zone improvement | pending | Measured with tools independent of Radio Sight (otherwise circular): `iperf3` throughput and ping packet loss from a laptop in the problem spot, before and after the placement change, same position. Report change in Mbps and loss. | 5+ runs before, 5+ after | | |
| Board power draw | pending | USB power meter inline on the board's cable. Average over 5 min idle and 5 min fully running. | 1 run each mode | | |

## What the measurements need
- **Contracts (Ivan):** every message carries a timestamp and a sequence number, so speed numbers can be computed from logs.
- **Session recorder (Alexander, `bus/`):** saves sessions to `data/sessions/` so `proof/` can replay them through the model.
- **Train/test split (everyone):** decide before recording which sessions are for training and which are held out for testing. Never test on training sessions.

## Honest limits
- Detects presence, zone and movement. It is a no-movement alert, not fall detection.
- Trained and tested in one room layout; accuracy in other rooms is not measured.
