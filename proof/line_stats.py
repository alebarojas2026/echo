"""Measured per-line evidence from recorded RSSI and independent timed operator labels."""

import argparse
from collections import defaultdict
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
import re
from statistics import median, pstdev

KINDS = ('empty', 'still', 'moving', 'object')
METHOD = '1 s non-overlapping medians; quiet = median empty window; jitter = median 1 s population SD'


def finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def analyze(recording, annotations, keep_windows=False):
    """No prediction-derived truth: intervals are confirmed by the operator, in seconds after meta."""
    rows = [json.loads(line) for line in Path(recording).read_text().splitlines() if line.strip()]
    note = json.loads(Path(annotations).read_text())
    metas = [r for r in rows if r.get('type') == 'meta']
    if len(metas) != 1 or not metas[0].get('session'):
        raise ValueError('exactly one named session meta is required')
    if not rows or any(r.get('src') != 'live' or r.get('v') != 2 or not finite(r.get('recv_t')) for r in rows):
        raise ValueError('only live v2 recordings with finite receive timestamps are measured evidence')
    if any(a['recv_t'] > b['recv_t'] for a, b in zip(rows, rows[1:])):
        raise ValueError('receive clock moved backwards; split and annotate a valid recording')
    if note.get('recording_sha256') != digest(recording) or note.get('session') != metas[0]['session']:
        raise ValueError('annotations must identify this recording by session and SHA256')
    if note.get('truth') != 'operator' or not re.fullmatch(r'[0-9a-f]{40}', note.get('commit', '')):
        raise ValueError('operator truth and full recorded board commit are required')
    intervals = note.get('intervals')
    if not isinstance(intervals, list) or not intervals:
        raise ValueError('confirmed intervals are required')
    origin = metas[0]['recv_t']
    end = (rows[-1]['recv_t'] - origin) / 1000
    previous = 0
    for span in intervals:
        a, b = span.get('start_s'), span.get('end_s')
        if (span.get('kind') not in KINDS or not finite(a) or not finite(b)
                or a < previous or b <= a or b > end):
            raise ValueError('intervals must be ordered, disjoint, and inside the recording')
        previous = b
    radio = defaultdict(list)
    for row in rows:
        if row.get('type') == 'rssi':
            if not isinstance(row.get('link'), str) or not finite(row.get('dbm')) or not -150 <= row['dbm'] <= 0:
                raise ValueError('invalid RSSI line or dBm')
            radio[row['link']].append(((row['recv_t'] - origin) / 1000, row['dbm']))
    duration = sum(s['end_s'] - s['start_s'] for s in intervals)
    result = []
    for link, points in sorted(radio.items()):
        windows = {k: [] for k in KINDS}
        jitter = {k: [] for k in KINDS}
        count = 0
        for span in intervals:
            a, b, kind = span['start_s'], span['end_s'], span['kind']
            selected = [(t, v) for t, v in points if a <= t < b]
            count += len(selected)
            bins = defaultdict(list)
            for t, value in selected:
                bins[int(t - a)].append((t, value))
            for index, batch in bins.items():
                start = a + index
                # Reject partial windows and gaps, rather than bridging a stopped sensor.
                times = [start, *[t for t, _ in batch], start + 1]
                if start + 1 > b or len(set(times[1:-1])) < 2 or max(y-x for x,y in zip(times,times[1:])) > 0.6:
                    continue
                values = [v for _, v in batch]
                windows[kind].append(median(values))
                jitter[kind].append(pstdev(values))
        row = summarize(link, windows, jitter, count, duration)
        if keep_windows: row.update(_windows=windows, _jitter=jitter)
        result.append(row)
    return {'session': metas[0]['session'], 'source': 'live', 'commit': note['commit'],
            'recording_sha256': digest(recording), 'annotations_sha256': digest(annotations),
            'measured_at': datetime.fromtimestamp(rows[-1]['recv_t']/1000, timezone.utc).isoformat(),
            'method': METHOD, 'lines': result, 'started_at_ms': origin, 'ended_at_ms': rows[-1]['recv_t'],
            'duration_s': duration, 'group': note.get('group'), 'layout_sha256': note.get('layout_sha256'),
            'layout_note': note.get('layout_note')}


def summarize(link, windows, jitter, count, duration):
    empty = windows['empty']
    people = windows['still'] + windows['moving']
    quiet = median(empty) if empty else None
    drops = [quiet - p for p in people] if quiet is not None else []
    return {'link': link, 'quiet_dbm': quiet,
                   'person_drop_db': [min(drops), max(drops)] if drops else None,
                   'separation_db': min(empty) - max(people) if empty and people else None,
                   'empty_dip_db': max(0, quiet - min(empty)) if empty else None,
                   'readings_per_s': count / duration if count else None,
                   'readings': count, 'duration_s': duration,
                   'windows': {k: len(v) for k,v in windows.items()},
                   'jitter_db': {k: median(v) if v else None for k,v in jitter.items()}}


def group_reports(reports):
    groups, output = defaultdict(list), []
    for report in reports:
        if report['group'] is None:
            output.append(report)
        else:
            if not isinstance(report['group'], str) or not report['group'].strip():
                raise ValueError('group needs a name')
            groups[report['group']].append(report)
    for name, members in groups.items():
        members.sort(key=lambda r: r['started_at_ms'])
        # The layout file's hash, or, when the board's file was not kept, the operator's own words for the
        # placement (layout_note): the same on every recording of the group, and printed under the table.
        note = members[0].get('layout_note')
        worded = members[0]['layout_sha256'] is None and isinstance(note, str) and len(note.strip()) >= 20
        if len({r['commit'] for r in members}) != 1 or len({(r['layout_sha256'], r.get('layout_note')) for r in members}) != 1 or not (
                worded or re.fullmatch(r'[0-9a-f]{64}', members[0]['layout_sha256'] or '')):
            raise ValueError('group recordings need the same board commit and layout SHA256 (or the same layout_note)')
        if any(a['ended_at_ms'] > b['started_at_ms'] for a,b in zip(members,members[1:])):
            raise ValueError('group recordings overlap in time')
        report = dict(members[-1], session=name, lines=[], sources=[
            {k:r[k] for k in ('session','recording_sha256','annotations_sha256')} for r in members])
        report.pop('recording_sha256'); report.pop('annotations_sha256')
        report['started_at_ms'] = members[0]['started_at_ms']
        report['duration_s'] = sum(r['duration_s'] for r in members)
        links = sorted({row['link'] for r in members for row in r['lines']})
        for link in links:
            rows = [row for r in members for row in r['lines'] if row['link'] == link]
            windows = {k:[v for row in rows for v in row['_windows'][k]] for k in KINDS}
            jitter = {k:[v for row in rows for v in row['_jitter'][k]] for k in KINDS}
            report['lines'].append(summarize(link,windows,jitter,sum(r['readings'] for r in rows),report['duration_s']))
        output.append(report)
    for report in output:
        for row in report['lines']:
            row.pop('_windows',None); row.pop('_jitter',None)
    return output


def table(reports):
    from proof.render_table import cell
    if not reports:
        return []
    out = ['', '## Recorded per-line evidence', '',
           '| Session / line | Person drop dB | Separation dB | Largest empty dip dB | Readings/s | Jitter still / moving / object dB | Valid 1 s windows empty / still / moving / object | Date | Board commit |',
           '|---|---|---|---|---|---|---|---|---|']
    def number(value):
        if value is None:
            return '__'
        if not finite(value):
            raise ValueError('nonfinite line evidence')
        return f'{value:.2f}'
    provenance = []
    for report in reports:
        if report.get('source') != 'live' or report.get('method') != METHOD:
            raise ValueError('only measured line reports are publishable')
        sources = report.get('sources', [report])
        if not sources or not re.fullmatch(r'[0-9a-f]{40}', report.get('commit', '')) or any(
                not re.fullmatch(r'[0-9a-f]{64}', source.get(k, '')) for source in sources for k in ('recording_sha256','annotations_sha256')):
            raise ValueError('line report provenance is missing')
        datetime.fromisoformat(report['measured_at'])
        for row in report['lines']:
            drop = row['person_drop_db']
            cells = [report['session'] + ' / ' + row['link'],
                     '__' if drop is None else ' to '.join(number(v) for v in drop),
                     number(row['separation_db']), number(row['empty_dip_db']), number(row['readings_per_s']),
                     ' / '.join(number(row['jitter_db'][k]) for k in KINDS[1:]),
                     ' / '.join(str(row['windows'][k]) for k in KINDS), report['measured_at'], report['commit']]
            out.append('| ' + ' | '.join(cell(v) for v in cells) + ' |')
        for source in sources:
            provenance.append(f"{cell(source['session'])}: recording SHA256 `{source['recording_sha256']}`; labels SHA256 `{source['annotations_sha256']}`.")
        if report.get('group') and report.get('layout_sha256'):
            provenance.append(f"Group {cell(report['group'])}: layout SHA256 `{report['layout_sha256']}`.")
        elif report.get('group'):
            provenance.append(f"Group {cell(report['group'])}: the board's layout file was not kept; the operator's note: {cell(report['layout_note'])}")
    out.extend(['', *provenance])
    out.extend(['', METHOD + '. Separation = weakest empty RSSI minus strongest person RSSI; a negative value means overlap. '
                'Rate counts all readings over all labelled seconds, including gaps. Missing/partial windows are excluded from drop and jitter, never treated as empty.'])
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pair', nargs=2, action='append', required=True, metavar=('RECORDING', 'INTERVALS'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    reports = [analyze(*pair, keep_windows=True) for pair in args.pair]
    identities = [r['recording_sha256'] for r in reports]
    if len(set(identities)) != len(identities):
        raise ValueError('duplicate recording')
    reports = group_reports(reports)
    table(reports)  # Validate before replacing any existing report.
    args.output.write_text(json.dumps(reports, indent=2, allow_nan=False) + '\n')


if __name__ == '__main__':
    main()
