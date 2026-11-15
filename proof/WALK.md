# Guided recordings

Alexander runs `python -m proof.walk <unique-session> <purpose> <walker>` against
the board brain WebSocket. Use pseudonymous walker ids. The coach sends only v2
commands and prints one prompt/countdown at a time; it writes no files, images
or measurements. The bus and brain keep their usual session-recording roles.
Ctrl-C sends label_mode off and record_stop before exiting when the connection
is still available. Confirm the board reports recording before following prompts.
The client continuously drains incoming states on a receiver thread during the
countdowns, so the state queue cannot prevent keepalive replies. The receiver
closes and joins when the walk ends or is interrupted.

The existing-session file check works only when this runs on the board from the
bus's own checkout. A remote coach cannot inspect the board's session files;
Alexander must ensure its id has never been used there before starting.

Each script starts with 20 s nobody inside, with label_mode off. The zones, their
centres and names come from the layout (`radio/nodes.json`, or the file named by
`RADIO_SIGHT_NODES`), so the prompts follow the layout in use. Each zone visit is a
5 s walk and 10 s standing still, and every walk ends with 20 s nobody inside.

- **Desk layout** (a 1.6 x 0.6 m strip in front of the desk, zones 1 Left at
  (0.4, 0.3) and 2 Right at (1.2, 0.3)): one pass over two zones is too short to
  train on, so train goes Left, Right, Left, Right, then 8 s on the middle mark (the
  split line, x = 0.8 m), then out; heldout goes Right, Left, Right, Left, middle,
  out; crowd is Right, Left with truth commands at the standing prompts. Prompts say
  "the strip" and "one step from the desk". The tray goes on T1 on the desk, 12 cm
  from Pi A; the walker then steps back out of the strip.
- **Square layout** (2 x 2 m, four zones, as before): NW/Bed (0.5,1.5), NE/Chair
  (1.5,1.5), SW/Hall (0.5,0.5), SE/Bathroom (1.5,0.5), in metres east/north from the
  SW origin. Training order is 1,3,2,4; heldout is 4,2,3,1; crowd is 3,4,1,2.

Object mode gives time to place the tray at T1 and step out before 15 s object
labels, then remove it and record clear floor. Only the object hold uses object
mode. Do not stand inside during that hold.

Plan at least three training people and five heldout sessions before recording.
For example w1/w2/w3 each make separate training walks, then make five new
heldout walks across those people; add an unseen w4 if available. These are
collection targets, not measured counts or proof claims. Score only recordings
declared heldout in advance; never reuse a physical walk, file, or session id in
both groups. Record object training separately, then new object trials declared
heldout for evaluation with `python -m proof.walk <new-id> heldout <walker> --object-trial`.
Crowd/game runs are never part of the heldout score.

Use loose measured floor markers during the build. Alexander tapes and repeats
calibration, the 20 s baseline and training in the presentation room later.
The coach's 20 s empty periods are recorded observations, not a replacement for
the explicit baseline command and valid baseline artifact. Run teacher.quality
before using a session. Verify the real label-mode mount and camera frame rate.
