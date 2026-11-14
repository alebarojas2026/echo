# Camera label quality

Run `python -m teacher.quality <recorded-session.jsonl>` before using its labels
for training. All timing uses recv_t. The report contains processed-label rate,
clipped share, empty-frame share, gaps over 1 s and RMS foot-point jitter in
continuous same-zone runs labeled still. Empty/clipped frames and moving people
do not enter the jitter statistic. Runs need at least three points; camera gaps
over 0.5 s split them. Missing evidence is null, never a perfect zero.

The default flags (below 5 Hz, clipped share over 10%, jitter over 0.1 m) are
configurable setup heuristics, not measured accuracy claims. Use a deliberately
standing-still recording to assess jitter; the report cannot establish ground
truth from camera predictions alone. Keep simulated reports out of proof.json.
