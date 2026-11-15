# Proof

Every number shown on screen or in the pitch has a row here: what was measured, how, on how many people or sessions, when, and on which commit.

| Number | Value | Method | N | Date | Commit |
|---|---|---|---|---|---|
| Radio vs camera zone agreement | __ | Held-out sessions with the camera labeling and the model predicting from radio only. Compare predictions to labels using the zones in radio/nodes.json, including empty. Report agreement, its interval, the confusion matrix and the measured baseline; this makes no claim about sides the active layout does not define. | __ | __ | __ |
| Presence accuracy | __ | Ten held-out cycles: 1 min empty, 1 min occupied; camera unplugged, a walker absent from the lesson. Compare radio decisions once per observed second with a written enter/leave log; show the always-empty score on the same seconds. | __ | __ | __ |
| Person vs object accuracy | __ | Place a still object (box, chair, water jug) in the zone, then a person. Count how often each is labeled obstruction vs person. | __ | __ | __ |
| Time to train on the board | __ | Wall-clock time on the UNO Q from training start to model ready. Report the median. | __ | __ | __ |
| Time per decision | __ | Time around the prediction step on the board. Report median and 95th percentile. | __ | __ | __ |
| End-to-end update latency | pending | Slow-motion phone video with the person and the screen in one shot. Count frames from the step into the zone to the screen changing. | 10+ trials | | |
| No-movement alert latency | pending | Same video method: time from the person freezing to the alert, minus the configured wait period. | 5+ trials | | |
| Dead-zone improvement | pending | Measured with tools independent of Radio Sight (otherwise circular): `iperf3` throughput and ping packet loss from a laptop in the problem spot, before and after the placement change, same position. Report change in Mbps and loss. | 5+ runs before, 5+ after | | |
| Board power draw | __ | USB power meter inline on the board's cable. Average over 5 min idle and 5 min fully running. | __ | __ | __ |
| Images stored | __ | After a full lesson, audit project data, the App Lab app folder, teacher host mounts and its full filesystem using teacher/privacy.py suffixes. Missing scope fails the audit. See proof/MANUAL.md. | __ | __ | __ |
| Bytes sent outside our network | __ | Board egress counter around a full rehearsal, with no IPv4 or IPv6 default route. Local laptop/phone traffic is allowed. See proof/MANUAL.md. | __ | __ | __ |

## What the measurements need
- **Contracts (Ivan):** every message carries a timestamp and a sequence number, so speed numbers can be computed from logs.
- **Session recorder (Alexander, `bus/`):** saves sessions to `data/sessions/` so `proof/` can replay them through the model.
- **Train/test split (everyone):** decide before recording which sessions are for training and which are held out for testing. Never test on training sessions.

## Honest limits
- Detects presence, zone and movement. The no-movement alert notices that someone has stopped moving, not why.
- Trained and tested in one room layout; accuracy in other rooms is not measured.

<!-- proof-json:start -->

## Additional proof.json measurements

| Number | Value | Method | N | Date | Commit |
|---|---|---|---|---|---|
| Threshold zone baseline | __ | Fixed 3 dB strongest-link baseline | __ | __ | __ |
| False check-in, alert and object events per minute | __ | False events / observed empty or still minutes; see proof/FALSE_ALARMS.md | __ | __ | __ |
| Bytes sent out | __ | Measured network egress | __ | __ | __ |
| Images stored | __ | Measured storage audit | __ | __ | __ |
| Models on board | __ | Installed model inventory | __ | __ | __ |
| Entry detection within 2 s | __ | Independent heldout entries; see proof/SECURITY.md | __ | __ | __ |
| Armed intrusion detection | __ | Independent heldout entries; see proof/SECURITY.md | __ | __ | __ |
| False presences per hour | __ | Captured events during observed empty time | __ | __ | __ |
| False intrusions per hour | __ | Captured events during observed empty time | __ | __ | __ |
| Passed-by events per armed hour | __ | Captured events during observed armed time | __ | __ | __ |
| Outside-only passes raising intrusion | __ | Confirmed operator trials; see proof/TRIALS.md | __ | __ | __ |
| Crowd no-movement alerts | __ | Confirmed operator trials; see proof/TRIALS.md | __ | __ | __ |
| Tamper detected within 5 s | __ | Confirmed operator trials; see proof/TRIALS.md | __ | __ | __ |
| Crowd intrusions per hour | __ | Events / observed armed exposure | __ | __ | __ |
| False tamper events per hour | __ | Events / observed armed exposure | __ | __ | __ |
| Lesson shortest | __ | Start to 8 of last 10; recorded board states | __ | __ | __ |
| Lesson longest | __ | Start to 8 of last 10; recorded board states | __ | __ | __ |
| Lesson median | __ | Start to 8 of last 10; recorded board states | __ | __ | __ |
| Post-unplug zone agreement | __ | Operator-confirmed positions; camera off | __ | __ | __ |

## Recorded per-line evidence

| Session / line | Person drop dB | Separation dB | Largest empty dip dB | Readings/s | Jitter still / moving / object dB | Valid 1 s windows empty / still / moving / object | Date | Board commit |
|---|---|---|---|---|---|---|---|---|
| in the open / pi5>pi5b:ble | -4.00 to 13.00 | -16.00 | 12.00 | 2.68 | 1.70 / 2.16 / __ | 286 / 45 / 7 / 0 | 2026-11-15T06:50:56.604000+00:00 | 4d87ebddd6de2c4e9e8062b815072568417776e3 |
| in the open / pi5>pi5b:wifi | 11.00 to 24.00 | 9.00 | 2.00 | 24.97 | 0.54 / 2.48 / __ | 473 / 65 / 19 / 0 | 2026-11-15T06:50:56.604000+00:00 | 4d87ebddd6de2c4e9e8062b815072568417776e3 |
| in the open / pi5>unoq:ble | -1.00 to 2.00 | -2.00 | 1.00 | 5.71 | 0.83 / 1.22 / __ | 451 / 63 / 17 / 0 | 2026-11-15T06:50:56.604000+00:00 | 4d87ebddd6de2c4e9e8062b815072568417776e3 |
| in the open / pi5>unoq:wifi | -1.00 to 1.00 | -2.00 | 1.00 | 22.32 | 0.76 / 0.76 / __ | 473 / 65 / 19 / 0 | 2026-11-15T06:50:56.604000+00:00 | 4d87ebddd6de2c4e9e8062b815072568417776e3 |
| in the open / pi5b>pi5:ble | -4.00 to 9.00 | -18.50 | 14.50 | 3.25 | 1.93 / 2.87 / __ | 341 / 46 / 15 / 0 | 2026-11-15T06:50:56.604000+00:00 | 4d87ebddd6de2c4e9e8062b815072568417776e3 |
| in the open / pi5b>unoq:ble | -4.00 to 10.00 | -11.00 | 7.00 | 5.38 | 3.14 / 4.13 / __ | 445 / 60 / 16 / 0 | 2026-11-15T06:50:56.604000+00:00 | 4d87ebddd6de2c4e9e8062b815072568417776e3 |
| Pi B in a backpack / pi5>pi5b:ble | 1.50 to 7.50 | -9.50 | 11.00 | 2.85 | 1.47 / __ / __ | 62 / 29 / 0 / 0 | 2026-11-15T06:56:40.159000+00:00 | 4d87ebddd6de2c4e9e8062b815072568417776e3 |
| Pi B in a backpack / pi5>pi5b:wifi | 18.00 to 24.00 | 16.00 | 2.00 | 24.97 | 0.47 / __ / __ | 105 / 46 / 0 / 0 | 2026-11-15T06:56:40.159000+00:00 | 4d87ebddd6de2c4e9e8062b815072568417776e3 |
| Pi B in a backpack / pi5>unoq:ble | -0.50 to 2.00 | -2.50 | 2.00 | 5.72 | 1.22 / __ / __ | 103 / 46 / 0 / 0 | 2026-11-15T06:56:40.159000+00:00 | 4d87ebddd6de2c4e9e8062b815072568417776e3 |
| Pi B in a backpack / pi5>unoq:wifi | -1.00 to 0.00 | -2.00 | 1.00 | 22.35 | 0.73 / __ / __ | 105 / 46 / 0 / 0 | 2026-11-15T06:56:40.159000+00:00 | 4d87ebddd6de2c4e9e8062b815072568417776e3 |
| Pi B in a backpack / pi5b>pi5:ble | -0.50 to 13.50 | -6.00 | 5.50 | 3.54 | 1.69 / __ / __ | 82 / 34 / 0 / 0 | 2026-11-15T06:56:40.159000+00:00 | 4d87ebddd6de2c4e9e8062b815072568417776e3 |
| Pi B in a backpack / pi5b>unoq:ble | 1.00 to 14.00 | -2.00 | 3.00 | 5.41 | 4.50 / __ / __ | 99 / 41 / 0 / 0 | 2026-11-15T06:56:40.159000+00:00 | 4d87ebddd6de2c4e9e8062b815072568417776e3 |
| Pi B on a chair seat / pi5>pi5b:ble | 0.00 to 16.00 | -2.50 | 2.50 | 3.01 | 1.25 / __ / __ | 42 / 21 / 0 / 0 | 2026-11-15T07:01:35.236000+00:00 | 4d87ebddd6de2c4e9e8062b815072568417776e3 |
| Pi B on a chair seat / pi5>pi5b:wifi | 2.00 to 4.00 | 1.00 | 1.00 | 25.00 | 0.20 / __ / __ | 59 / 45 / 0 / 0 | 2026-11-15T07:01:35.236000+00:00 | 4d87ebddd6de2c4e9e8062b815072568417776e3 |
| Pi B on a chair seat / pi5>unoq:ble | -1.00 to 1.00 | -3.00 | 2.00 | 5.89 | 1.17 / __ / __ | 56 / 42 / 0 / 0 | 2026-11-15T07:01:35.236000+00:00 | 4d87ebddd6de2c4e9e8062b815072568417776e3 |
| Pi B on a chair seat / pi5>unoq:wifi | -1.00 to 1.50 | -2.00 | 1.00 | 22.25 | 0.71 / __ / __ | 59 / 45 / 0 / 0 | 2026-11-15T07:01:35.236000+00:00 | 4d87ebddd6de2c4e9e8062b815072568417776e3 |
| Pi B on a chair seat / pi5b>pi5:ble | 0.00 to 12.00 | -3.00 | 3.00 | 3.55 | 2.08 / __ / __ | 50 / 34 / 0 / 0 | 2026-11-15T07:01:35.236000+00:00 | 4d87ebddd6de2c4e9e8062b815072568417776e3 |
| Pi B on a chair seat / pi5b>unoq:ble | 2.50 to 16.00 | 0.00 | 2.50 | 5.22 | 2.47 / __ / __ | 56 / 42 / 0 / 0 | 2026-11-15T07:01:35.236000+00:00 | 4d87ebddd6de2c4e9e8062b815072568417776e3 |

flutter-062954: recording SHA256 `c570885bf9dd311844ff2dc7f3275157818e3e04855a8331fdfc05695c4213f8`; labels SHA256 `7767b556df6160cf95f6e04a335204cf11a98d33fff3a9189823c44d3bf6b55e`.
flutter-063013: recording SHA256 `7aec997625c256c76a63fb6b1b56d2d7b43b85537fba2ecd6c52836dc5fb6143`; labels SHA256 `748ffae6022908c76742cd264ea0e84ffa5493f0c1a6567a70c4fea784e8c1ee`.
flutter-063033: recording SHA256 `fa5ec873d1fc1f228f44e4c8b902b18f109d1892617f5e7407133b0066c47c45`; labels SHA256 `e5248ffa8664bf13bcb0516c276bb7300ed92a8dcc685b181377f0ff9764e2be`.
flutter-063052: recording SHA256 `1c4fbb72ae8e48e2312dfc36e1f99c177cdd3e4a6c12c24fa9048da34880cfe7`; labels SHA256 `535b07679c4554f99c4671430a374c79fed3114479e72b626725738a7a194c11`.
flutter-063111: recording SHA256 `b94191045eb0fe6af00bd0450e4b71c22ab71a84c3d7981ecf828cbe4f8ce12c`; labels SHA256 `eea9c09675ee1e296cf69b9eb7edd9b21c5a5349a6be6db5c5cdac72f96d9fc7`.
flutter-063131: recording SHA256 `a3fb64af52a6d4601f799968265687aaf7f068942931ccc0065664422e34a2f8`; labels SHA256 `538b9851eb3897d2c7094646a037fc80e0e3fc4636c651098cd8135b4c809374`.
flutter-063151: recording SHA256 `056a450e735d913a2f47068874ad11b4644801783b27295849ebec9f9d481101`; labels SHA256 `197ab885b29cb6ac02e133a83a70d5dfdd44ba38e9651863cfefb84879f42fdf`.
flutter-063210: recording SHA256 `75b3c610b849f8b8bb3dcacd1b73ef414c3848bfaa2f7fd8d9bb660b7b2b7950`; labels SHA256 `e747bc8469e8bb0a1d38b1f1f229bc3b6ee6ea9f13f222505d036101f1b50a34`.
flutter-063229: recording SHA256 `f5a5f72dd2435505434689e644942d6ca9aa45dfb47a4b86b7cbc0774a8c3344`; labels SHA256 `fb4219d34c799ff4e00d9f06d22e9d6da9d3cd002263be04e289aa8c0ffbd7d7`.
flutter-063248: recording SHA256 `3007e21a1c8ee44e0a0003e8a75b3e554351ae5e24dc1a9ac936491fbc89b235`; labels SHA256 `f8d37ed594d385c12d00daee4139f093bc57dd59133aaa963ef34b1b74e5110a`.
flutter-063308: recording SHA256 `53a3b03c208f1f3e6272dfe560d7161aafd4a6f96152a3a96cb47716a4ccdf60`; labels SHA256 `53a079cb960f55f9892cb18d75fc80e096440090f039793aa3266a5d5bd33408`.
flutter-063327: recording SHA256 `496dd616b288d12493b2197392a8670228e692ba390337671106bdaff8109706`; labels SHA256 `7f9dc4d2e6bde6ae4b2643840aa56df0c232dce30544ffe6200cb47878f6a812`.
flutter-063607: recording SHA256 `66a7acea546cfda772d892f04f918be91ac163e0fa33bb9b9d69e8b1d9a1554b`; labels SHA256 `6ab3fdfe291083efbf147a68de7f7377f522af4f26a05aa9333ebdc3e11008ef`.
flutter-065007: recording SHA256 `b3a9b4073d143f5a31f8ddac4bc6133e2b4962fa94396e3258a720ba8b65cd7e`; labels SHA256 `ac1b3a027c617170bc6af166cb7cdf659ee0d9795b3db45a04c34416f14e7d71`.
flutter-065036: recording SHA256 `a1ae96e83f7e94cafef58fb17b404fc19c7ff62e33f0004999a6d067b7702130`; labels SHA256 `810eaf32922f77ed069ad81787dd79adbdcbf484d1c9a15baa9cb71eb86228da`.
Group in the open: the board's layout file was not kept; the operator's note: the board and Pi A side by side on one desk, Pi B across the gap at desk height, in the open
flutter-065217: recording SHA256 `38b78a415eeede448a891367fa4b535fc1ea695950b5b12ea08b12fc3cbf23cb`; labels SHA256 `d1b0f431ad4732ce8d09537f38d62523521662cb7c3fa437c182c9353d520ac8`.
flutter-065327: recording SHA256 `a5d0701af316f9e631649b66985b88cb1d6cb01ff89ecc2261b5b21de9b878f8`; labels SHA256 `3ce84337fb1712be02a561988ef76ed4fcc74d475d1b8c2b5eb6fb46ab9e5c50`.
flutter-065348: recording SHA256 `8ed79c340d60b3aba0701c777168a422b2a205894fba6b8ea393b4b3bb4a7ce3`; labels SHA256 `69f8c9220dca775e022cc31e5880ef79974d6eaed9b4b40ec9e7a021cba86a67`.
flutter-065408: recording SHA256 `31bd2043907ed5c814a660706f0e9dc54709d59fab08d8e1ac2deca408506112`; labels SHA256 `f58b0c889f207cb9192a57041b087596a0653e6c3a594c4d3f81c96f6e41d707`.
flutter-065428: recording SHA256 `1cdf21383c88843779af5a6d257a2f86930dfea66c353dcce6b1a1df2f675ff0`; labels SHA256 `dede96ee1ebe6f62c6ec82177729d2ca1e79baa783372d04042721ba039c697e`.
flutter-065448: recording SHA256 `4623407f4f56261219e343d735bb2abaa3c0db698f0306bcb2212237ac241b4e`; labels SHA256 `f98f6d6d9fa0f40cfde1405fd8f0d61438df90c5ef90ea0d7921d6201b400976`.
flutter-065508: recording SHA256 `a437942f5604fa6cf8dfd8de75629acb319fef68f95ab675c926c4ef1652aeb4`; labels SHA256 `9508faf94be4bac7a998574688c120f413c11b3b9dfc51ceab60d51fb9f7344a`.
flutter-065529: recording SHA256 `518eb0a81bf437e4dc6e5a39edb4103adaa9b9d0777b037796a0d5f51ee499ae`; labels SHA256 `ff2f28948beb422cd7302d25926e8ba9c98f86bdd12b5b3bef7ad3f8b2b81627`.
flutter-065549: recording SHA256 `f4bfcc16acdc3ba69c5cfcb15df3ec6ec0ad3f9c22a8a9324fa3f695c3b67838`; labels SHA256 `325ce3f6bc8ea723acd5ec574ceb39f165c87c37734bbb27b939c4ab487fd2cb`.
flutter-065609: recording SHA256 `2bf8611fdab3de9156fc58bda21c7800dbe0232bc1588342a8b5ce0a5841f604`; labels SHA256 `2764c2da0204efd793e85be4ca625858678866a48473cf5a6cb73542891872e1`.
flutter-065630: recording SHA256 `3774afaf942d075bf1d2b98561d20c1f4c5ca6edadf8fe716f180ff779fec468`; labels SHA256 `d5b752d5848511685e2a435b221b48c0c1fab0d85a29711db2c7f45912676234`.
Group Pi B in a backpack: the board's layout file was not kept; the operator's note: the same desk and gap, with Pi B hidden inside a backpack
flutter-065757: recording SHA256 `31ac97ff636aaaf28f176de37c4303a78dc66f165730ef9beb946ebecc6efe11`; labels SHA256 `5b0cd3884ddadfe82f01fbe8841d986d2ad7a5e0d459675ec11b265b44af0cb4`.
flutter-065822: recording SHA256 `b91bbdf78870f20a7e1bb3c507e22dcd6d72b50a653b07a6e65ad5a351900aae`; labels SHA256 `3e7804d5d26ada70ccf2eabb0ab5932458143e89a89144e9a8e477ecbebca780`.
flutter-065842: recording SHA256 `4eae13489591b5b431e550b0f91822d0ae261db5abbbc23739525d3111f2a52b`; labels SHA256 `846545fc03374354d6b2b5c0bceaaeccd8caaf475dc6c99b71be09386e82b119`.
flutter-065903: recording SHA256 `3be89344b1c85876419c080b496d72cd62e3236f6b9ca0bd6fcaff5cccd7061c`; labels SHA256 `5dfa73f079d24c13d5dfd4299ce68e590fd285d7b9ee1aadbccca4670432cef5`.
flutter-065923: recording SHA256 `6af5602ec0073eeeb88db29ccfc49397a1fb6225e7905886c5eac76da1395a70`; labels SHA256 `9ee4ce17b29dc8ad2b434eb6e3ffac4bfe0e50265d34a7f588685734182acbc2`.
flutter-065943: recording SHA256 `76efac6b81e3ed2f73bf7baef2d1e47341784d891b231a2ba286e3124ba594ba`; labels SHA256 `585317675b86a64818c1acb33a50b4418c6732038960a0170b1019d89acd6698`.
flutter-070003: recording SHA256 `f59e02b0f2702138021e3ba64b2f03c54ea4e25e1ccb08208964dd15f13fad01`; labels SHA256 `6d70aff8e9073953001fd96f3126df1c75858e5455407b564dbfd332ebcdc10b`.
flutter-070023: recording SHA256 `38127462715ff0e8de61bed348e2a7af10605257404ec3f90bc43e54b0ce1f76`; labels SHA256 `5319584872de85440dd21fbd7ee9481a2f2ec05bcb22fbefe006aebd960c76b9`.
flutter-070044: recording SHA256 `f1c4536b4d6357aef15c79fffee0caaa57497ab7302684a00098ab04a2d56295`; labels SHA256 `cf30ee3ec740b0157d76a7e74f198337b65a8624188319dd0a00ffe226b2f071`.
flutter-070105: recording SHA256 `08bbaa36d456b23bc8d748869444c406098898a70a6701374327816bfbc142c8`; labels SHA256 `938e040ba924251bf8e38a9a478dc278f9ecbffdd0401725a9352853326906e6`.
flutter-070125: recording SHA256 `ba4ea768eae3a2019c0422f556e40a17ef2e67966568c921fcf286892b16fed6`; labels SHA256 `e1f825848a0821a9c627b2377d9d4aef78188a81a5213b3355dba69e9300ce70`.
Group Pi B on a chair seat: the board's layout file was not kept; the operator's note: the same desk and gap, with Pi B low on a chair seat (the placement that fails)

1 s non-overlapping medians; quiet = median empty window; jitter = median 1 s population SD. Separation = weakest empty RSSI minus strongest person RSSI; a negative value means overlap. Rate counts all readings over all labelled seconds, including gaps. Missing/partial windows are excluded from drop and jitter, never treated as empty.

## Replayed from recordings taken on the kit

| Number | Value | Method | N | Recorded | Brain build |
|---|---|---|---|---|---|
| Presence found (10-second stands) | 10 of 10 stands found; with this few trials the true rate is probably between 69% and 100% | one person, one night, replayed through the brain from recordings taken on the kit. Found = the brain said somebody for 0.3 s in a row during the stand. | 10 stands (5 in the open; 5 with Pi B hidden in a backpack) | 2026-11-15 UTC | 4b9036d |
| Found, in the open | 5 of 5 stands found; with this few trials the true rate is probably between 47% and 100% | one person, one night, replayed through the brain from recordings taken on the kit. | 5 stands | 2026-11-15 UTC | 4b9036d |
| Found, with Pi B hidden in a backpack | 5 of 5 stands found; with this few trials the true rate is probably between 47% and 100% | one person, one night, replayed through the brain from recordings taken on the kit. | 5 stands | 2026-11-15 UTC | 4b9036d |
| False presence per empty minute | 0 in 9.4 empty minutes (0 a minute); with this little time the true rate is probably under 0.4 a minute | one person, one night, replayed through the brain from recordings taken on the kit. Every moment the brain said somebody on an empty spot counts, however short; armed throughout: 0 intrusions, 0 passed-by, 0 arrivals said. | 14 empty recordings, 9.4 minutes | 2026-11-15 UTC | 4b9036d |
| Time from the signal crossing to the decision | 0.50 to 0.58 s (median 0.55 s) | one person, one night, replayed through the brain from recordings taken on the kit. From the first reading of a stand's recording to the brain saying somebody. The step-on itself was not recorded as an event, so the time a body takes to step in is not in this number. | 10 stands | 2026-11-15 UTC | 4b9036d |
| Standing still read as still | 167 of 170 decisions (one session: it shows it can work, not how often) | one person, one night, replayed through the brain from recordings taken on the kit. Ten decisions a second from 3 s into the session; decisions inside one session are not independent trials. The word "still" was first said 3.3 s into the recording, which began with the person already there. | 1 session | 2026-11-15 UTC | 4b9036d |
| Stepping about read as moving | 154 of 170 decisions (one session: it shows it can work, not how often) | one person, one night, replayed through the brain from recordings taken on the kit. Ten decisions a second from 3 s into the session; decisions inside one session are not independent trials. The word "moving" was first said 4.6 s into the recording, which began with the person already there. | 1 session | 2026-11-15 UTC | 4b9036d |
| Stated limit: Pi B low on a chair seat | 0 of 5 stands found; with this few trials the true rate is probably between 0% and 53% | one person, one night, replayed through the brain from recordings taken on the kit. It fails: with Pi B low the person takes too little off the line. Declared before any replay as a placement expected to fail; Pi B must be at about desk height. | 5 stands | 2026-11-15 UTC | 4b9036d |

Stated limits:
- One spot (the layout has 1 zone and one line that decides), one person, one night, one room.
- Pi B low on a chair seat: 0 of 5 stands found. It fails: with Pi B low the person takes too little off the line. Declared before any replay as a placement expected to fail; Pi B must be at about desk height. The brain said "object" for 20.2 s of those recordings.
- Walk-throughs, crossings to the side, standing behind the device, a thing left in the line: seen once, used for tuning, not a result.
- Not live: each recording is all-empty or all-person and they are joined end to end, so no real step-on or step-off is in these numbers.

Recorded on the kit the night of 14 November 2026 (board build `4d87ebd`); the last report recording ended 2026-11-15T07:01:35.236000+00:00. Played on 2026-11-15 through the brain of `4b9036d9f478a9c9c4922aceebf1c0c622344804` on the `gate` layout (SHA256 `b00e01ef20b7b466fe6b79c8b2ff395cfa448130c87757fd3710121b9734beb8`): line `pi5>pi5b:wifi`, on 7 dB, off 3 dB, moving at 2.5 dB of spread, still again under 1.5 dB, each held for 1.5 s before the word changes. The sessions were split into tuning and report before those settings were chosen; these rows use the report sessions only (37 of 58 recordings played). Ranges are exact (Clopper-Pearson for counts, Poisson for the rate), 95%, rounded outward. See proof/REPLAYED.md.

## Live on the kit (the board's own decisions, not replayed)

| Number | Value | Method | N | Recorded | Board build |
|---|---|---|---|---|---|
| Live: stands for which the board said an arrival | 10 of 10 stands found; with this few trials the true rate is probably between 69% and 100% | one person, one run, live on the kit: decisions made by the board at the time, not replayed. Counted from the arrivals and leavings the board said, as its narrator recorded them; 10 arrivals said for 10 stands, 0 too many. The board held each for 8.7 to 9.4 s. | 10 stands of about 10 s | 2026-11-15 UTC | fad7179 |
| Live: arrivals said on the empty spot afterwards | 0 in 2.0 empty minutes | one person, one run, live on the kit: decisions made by the board at the time, not replayed. The last 120 s of the same recording, with the spot left empty: 0 events of any kind said. The board's ten-times-a-second decisions were not recorded, so this is "no arrival said", not "no false presence". | 2.0 minutes | 2026-11-15 UTC | fad7179 |

flutter-102623: recording SHA256 `1ea2260380442cdfdfb2f21483e5303991d9c0d93e55ef8e15bd1a00a13b9527`. The truth is the operator's count (how many stands, how long empty); there is no timed log, so no delay and no per-second number comes from this run. See proof/said_live.py.

<!-- proof-json:end -->
