import json

import pytest

from proof import line_stats as L, render_table, run_all
from proof.provenance import empty_proof


def capture(tmp_path, values=None):
    values = values or [-40, -42, -50, -52, -48, -54, -55, -55]
    meta = dict(v=2, type='meta', recv_t=100000, src='live', session='desk', purpose='heldout')
    rows = [meta]
    for i, value in enumerate(values):
        for offset in (0, 250, 500, 750):
            rows.append(dict(v=2, type='rssi', src='live', recv_t=100000+i*1000+offset,
                             link='router>listener:wifi', dbm=value))
    rows.append(dict(meta, type='cam', recv_t=108000))
    recording = tmp_path/'desk.jsonl'
    recording.write_text('\n'.join(json.dumps(row) for row in rows))
    note = dict(session='desk', recording_sha256=L.digest(recording), truth='operator', commit='a'*40,
                intervals=[dict(start_s=i*2, end_s=i*2+2, kind=k) for i,k in enumerate(L.KINDS)])
    annotations = tmp_path/'desk.line-intervals.json'
    annotations.write_text(json.dumps(note))
    return recording, annotations, rows, note


def test_exact_measured_drops_separation_rates_and_state_jitter(tmp_path):
    recording, annotations, rows, note = capture(tmp_path)
    # Moving jitter is 2 dB within each second, while still/object windows are steady.
    for row in rows:
        if row.get('type') == 'rssi' and 104000 <= row['recv_t'] < 106000:
            row['dbm'] += 2 if row['recv_t'] % 500 else -2
    recording.write_text('\n'.join(json.dumps(row) for row in rows))
    note['recording_sha256'] = L.digest(recording); annotations.write_text(json.dumps(note))
    report = L.analyze(recording, annotations)
    row = report['lines'][0]
    assert row['quiet_dbm'] == -41 and row['person_drop_db'] == [7, 13]
    assert row['separation_db'] == 6 and row['empty_dip_db'] == 1
    assert row['readings_per_s'] == 4 and row['readings'] == 32
    assert row['windows'] == dict.fromkeys(L.KINDS, 2)
    assert row['jitter_db'] == dict(empty=0, still=0, moving=2, object=0)
    rendered = render_table.render('', empty_proof(), [report])
    assert '7.00 to 13.00' in rendered and '0.00 / 2.00 / 0.00' in rendered
    assert L.digest(recording) in rendered and 'a'*40 in rendered
    assert render_table.render(rendered, empty_proof(), [report]) == rendered


def test_overlap_is_negative_not_hidden_and_missing_states_stay_unknown(tmp_path):
    recording, annotations, _, note = capture(tmp_path, [-40,-50,-42,-43,-42,-44,-55,-55])
    note['intervals'] = note['intervals'][:2]; annotations.write_text(json.dumps(note))
    row = L.analyze(recording, annotations)['lines'][0]
    assert row['separation_db'] == -8
    assert row['jitter_db']['moving'] is None and row['jitter_db']['object'] is None
    note['intervals'] = note['intervals'][1:]; annotations.write_text(json.dumps(note))
    row = L.analyze(recording, annotations)['lines'][0]
    assert row['person_drop_db'] is None and row['empty_dip_db'] is None


def test_sensor_gaps_do_not_become_empty_windows_and_reduce_rate(tmp_path):
    recording, annotations, rows, note = capture(tmp_path)
    rows = [r for r in rows if r['type'] != 'rssi' or r['recv_t'] % 1000 == 0]
    recording.write_text('\n'.join(json.dumps(r) for r in rows))
    note['recording_sha256'] = L.digest(recording); annotations.write_text(json.dumps(note))
    row = L.analyze(recording, annotations)['lines'][0]
    assert row['readings_per_s'] == 1 and row['person_drop_db'] is None
    assert row['windows'] == dict.fromkeys(L.KINDS, 0)


@pytest.mark.parametrize('bad', ['sim','missing_src','clock','nan','hash','overlap','outside','predicted','commit'])
def test_bad_or_unattributed_evidence_is_rejected_without_replacing_report(tmp_path,bad):
    recording, annotations, rows, note = capture(tmp_path)
    if bad == 'sim': rows[2]['src'] = 'sim'
    if bad == 'missing_src': rows[2].pop('src')
    if bad == 'clock': rows[2]['recv_t'] = 0
    if bad == 'nan': rows[2]['dbm'] = float('nan')
    if bad == 'overlap': note['intervals'][1]['start_s'] = 1
    if bad == 'outside': note['intervals'][-1]['end_s'] = 9
    if bad == 'predicted': note['truth'] = 'brain'
    if bad == 'commit': note['commit'] = 'unknown'
    recording.write_text('\n'.join(json.dumps(r) for r in rows))
    note['recording_sha256'] = '0'*64 if bad == 'hash' else L.digest(recording)
    annotations.write_text(json.dumps(note))
    output = tmp_path/'proof.lines.json'; output.write_text('old')
    with pytest.raises(ValueError): L.main(['--pair',str(recording),str(annotations),'--output',str(output)])
    assert output.read_text() == 'old'


def test_pipeline_scores_line_only_recording_and_renders_without_fake_proof_values(tmp_path):
    recording, annotations, _, _ = capture(tmp_path)
    output, document = tmp_path/'proof.json', tmp_path/'PROOF.md'
    document.write_text('Numbers pending\n')
    commands, missing = run_all.plan(tmp_path, output, tmp_path/'baseline.json', document)
    assert [c[2] for c in commands] == ['proof.line_stats','proof.render_table']
    assert '--lines' in commands[-1] and missing
    L.main(commands[0][3:])
    import sys
    from unittest.mock import patch
    with patch.object(sys,'argv',['render_table',*commands[-1][3:]]): render_table.main()
    assert 'Recorded per-line evidence' in document.read_text()
    assert not output.exists()  # No invented classifier, timing or privacy evidence.
    with pytest.raises(ValueError, match='duplicate'):
        L.main(['--pair',str(recording),str(annotations),'--pair',str(recording),str(annotations),
                '--output',str(output)])


def group_capture(tmp_path, name, offset, kind):
    folder = tmp_path/name; folder.mkdir()
    recording, annotations, rows, note = capture(folder)
    for row in rows:
        row['recv_t'] += offset
        if row['type'] == 'meta': row['session'] = name
    recording.write_text('\n'.join(json.dumps(r) for r in rows))
    note.update(session=name, recording_sha256=L.digest(recording), group='same-placement',layout_sha256='b'*64,
                intervals=[s for s in note['intervals'] if s['kind'] == kind])
    annotations.write_text(json.dumps(note))
    return recording, annotations


def test_separate_empty_and_person_recordings_share_only_an_explicit_reference(tmp_path):
    first = group_capture(tmp_path,'empty',0,'empty')
    second = group_capture(tmp_path,'person',10000,'still')
    output = tmp_path/'report.json'
    L.main(['--pair',*map(str,first),'--pair',*map(str,second),'--output',str(output)])
    report = json.loads(output.read_text())[0]
    row = report['lines'][0]
    assert row['person_drop_db'] == [9,11] and row['separation_db'] == 8
    assert row['readings_per_s'] == 4 and len(report['sources']) == 2
    text = '\n'.join(L.table([report]))
    assert L.digest(first[0]) in text and L.digest(second[0]) in text and 'b'*64 in text
    assert '_windows' not in output.read_text()


@pytest.mark.parametrize('field,value',[('layout_sha256','c'*64),('layout_sha256',None),('commit','c'*40)])
def test_grouping_refuses_other_layouts_or_commits(tmp_path,field,value):
    first = group_capture(tmp_path,'empty',0,'empty')
    second = group_capture(tmp_path,'person',10000,'still')
    note = json.loads(second[1].read_text()); note[field] = value; second[1].write_text(json.dumps(note))
    with pytest.raises(ValueError,match='same board commit'):
        L.group_reports([L.analyze(*first,keep_windows=True),L.analyze(*second,keep_windows=True)])


def test_grouping_refuses_overlapping_captures(tmp_path):
    first = group_capture(tmp_path,'empty',0,'empty')
    second = group_capture(tmp_path,'person',1000,'still')
    with pytest.raises(ValueError,match='overlap'):
        L.group_reports([L.analyze(*first,keep_windows=True),L.analyze(*second,keep_windows=True)])


def test_annotated_line_sessions_cannot_leak_into_classifier_accuracy(tmp_path):
    recording, annotations, rows, note = capture(tmp_path)
    (tmp_path/'training.jsonl').write_text(json.dumps(dict(rows[0],session='training',purpose='train')))
    (tmp_path/'baseline.json').write_text('{}')
    recording.with_suffix('.states.jsonl').write_text('')
    commands, missing = run_all.plan(tmp_path,tmp_path/'proof.json',tmp_path/'baseline.json',tmp_path/'PROOF.md')
    assert [c[2] for c in commands] == ['proof.line_stats','proof.render_table']
    assert any('purpose=heldout' in item for item in missing)
