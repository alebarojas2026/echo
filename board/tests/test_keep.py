"""Backup and restore through fake ssh, with a real SQLite backup and file renames."""
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

import pytest

from board.tests.shell import BASH,posix

REPO = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(BASH is None,reason='needs bash and git')
FILES = ['model.pkl','baseline.json','place.json','baselines.jsonl']


def git(root,*args):
    return subprocess.check_output(['git','-c','user.name=test','-c','user.email=test@example.com',*args],cwd=root,text=True).strip()


@pytest.fixture
def setup(tmp_path):
    laptop,board = tmp_path/'laptop',tmp_path/'board'
    (laptop/'board').mkdir(parents=True)
    shutil.copy2(REPO/'board/keep.sh',laptop/'board/keep.sh')
    (board/'data/sessions').mkdir(parents=True)
    (board/'scripts').mkdir()
    (board/'scripts/demo_check.py').write_text('print("PASS restored demo path")\n')
    git(laptop,'init','-q');git(laptop,'add','-A');git(laptop,'commit','-qm','first')
    git(board,'init','-q');git(board,'add','scripts');git(board,'commit','-qm','first')
    for name in FILES: (board/'data/sessions'/name).write_text('original '+name)
    (board/'data/sessions/recording.jsonl').write_text('leave recordings alone')
    with sqlite3.connect(board/'data/sessions/store.db') as db:
        db.execute('create table evidence(value)');db.execute('insert into evidence values (7)')
    tools=tmp_path/'bin';tools.mkdir()
    scripts={'ssh':'#!/bin/sh\necho ssh >> "$FAKE_LOG"\nwhile [ "$1" = -o ]; do shift 2; done\nshift\nexec sh -c "$*"\n',
             'ip':'#!/bin/sh\necho "192.168.77.2 dev ${FAKE_INTERFACE:-eth-test}"\n',
             'sudo':'#!/bin/sh\n[ "$1" != -n ] || shift\nexec "$@"\n',
             'systemctl':'#!/bin/sh\necho "systemctl $*" >> "$FAKE_LOG"\n[ "$1" != stop ] || [ -z "${FAIL_STOP:-}" ]\n',
             'python':'#!/bin/sh\nif [ "$1" = -c ] && [ "${3:-}" = keep-ready ]; then echo readiness >> "$FAKE_LOG"; exit "${FAIL_READY:-0}"; fi\nexec "$REAL_PYTHON" "$@"\n'}
    for name,text in scripts.items():
        path=tools/name;path.write_text(text,newline='\n');path.chmod(0o755)
    return {'laptop':laptop,'board':board,'bin':tools,'log':tmp_path/'calls'}


def keep(s,*args,ok=True,**extra):
    env=dict(os.environ)
    for key in ['BOARD_USER','BOARD_REPO','BOARD_HOST','PI_HOST','KEEP_INTERFACE']: env.pop(key,None)
    env.update({'BOARD_USER':'operator','BOARD_REPO':posix(s['board']),'BOARD_HOST':'192.168.77.2',
                'FAKE_LOG':posix(s['log']),'FAKE_BIN':posix(s['bin']),'PYTHON':posix(s['bin']/'python'),
                'REAL_PYTHON':sys.executable,**extra})
    result=subprocess.run([BASH,'-c','PATH="$FAKE_BIN:$PATH" exec bash board/keep.sh "$@"','keep',*map(str,args)],
                          cwd=s['laptop'],env=env,text=True,capture_output=True)
    assert (result.returncode==0)==ok,result.stdout+result.stderr
    return result.stdout+result.stderr


def saved(s):
    return next(p for p in (s['laptop']/'data/keep').iterdir() if p.is_dir() and not p.name.startswith('.'))


def test_save_includes_live_sqlite_snapshot_and_no_recordings(setup):
    db=sqlite3.connect(setup['board']/'data/sessions/store.db')
    try:
        db.execute('pragma journal_mode=wal')
        db.execute('insert into evidence values (8)');db.commit()
        out=keep(setup,'save');folder=saved(setup)
        assert 'keep: saved' in out and 'recording.jsonl' not in [p.name for p in folder.iterdir()]
        assert sorted(p.name for p in folder.iterdir())==sorted(FILES+['store.db','COMMIT','CHECKSUMS'])
        with sqlite3.connect(folder/'store.db') as copy: assert copy.execute('select value from evidence').fetchall()==[(7,),(8,)]
        assert git(setup['laptop'],'check-ignore',str(folder/'model.pkl'))
    finally: db.close()


def test_restore_replaces_learned_files_and_checks_the_stack(setup):
    keep(setup,'save');folder=saved(setup)
    for name in FILES: (setup['board']/'data/sessions'/name).write_text('changed')
    with sqlite3.connect(setup['board']/'data/sessions/store.db') as db: db.execute('delete from evidence')
    out=keep(setup,'restore',folder)
    assert 'PASS restored demo path' in out and 'restored learned state' in out
    for name in FILES: assert (setup['board']/'data/sessions'/name).read_text()=='original '+name
    with sqlite3.connect(setup['board']/'data/sessions/store.db') as db: assert db.execute('select value from evidence').fetchall()==[(7,)]
    assert (setup['board']/'data/sessions/recording.jsonl').read_text()=='leave recordings alone'
    log=setup['log'].read_text()
    assert log.index('systemctl stop')<log.index('systemctl start')
    assert log.index('systemctl start')<log.index('readiness')


@pytest.mark.parametrize('setting',[{'BOARD_HOST':'10.42.0.1'},{'FAKE_INTERFACE':'wlan0'},{'PI_HOST':'hotspot-hop'}])
def test_hotspot_transport_is_refused_before_ssh(setup,setting):
    assert 'keep:' in keep(setup,'save',ok=False,**setting)
    assert not setup['log'].exists()


def test_corrupt_backup_is_refused_before_stopping_services(setup):
    keep(setup,'save');folder=saved(setup)
    (folder/'model.pkl').write_text('corrupt')
    out=keep(setup,'restore',folder,ok=False)
    assert 'checksum mismatch' in out and 'systemctl stop' not in setup['log'].read_text()


def test_restore_requires_the_saved_code_commit(setup):
    keep(setup,'save');folder=saved(setup)
    (setup['board']/'scripts/new.txt').write_text('next')
    git(setup['board'],'add','scripts');git(setup['board'],'commit','-qm','next')
    out=keep(setup,'restore',folder,ok=False)
    assert 'deploy the backup COMMIT' in out and 'systemctl stop' not in setup['log'].read_text()


def test_missing_learned_file_does_not_publish_a_partial_backup(setup):
    (setup['board']/'data/sessions/model.pkl').unlink()
    assert 'missing model.pkl' in keep(setup,'save',ok=False)
    assert not any(p.is_dir() for p in (setup['laptop']/'data/keep').iterdir())


def test_failed_service_stop_does_not_replace_data_or_start_services(setup):
    keep(setup,'save');folder=saved(setup)
    (setup['board']/'data/sessions/model.pkl').write_text('current')
    out=keep(setup,'restore',folder,ok=False,FAIL_STOP='1')
    assert 'restore incomplete' in out
    assert (setup['board']/'data/sessions/model.pkl').read_text()=='current'
    assert 'systemctl start' not in setup['log'].read_text()


def test_failed_readiness_does_not_report_a_successful_restore(setup):
    keep(setup,'save');folder=saved(setup)
    out=keep(setup,'restore',folder,ok=False,FAIL_READY='1')
    assert 'PASS restored demo path' not in out and 'restored learned state and checked' not in out


def test_wired_environment_can_disable_a_saved_proxy_hop(setup):
    (setup['laptop']/'.env').write_text('PI_HOST=hotspot-hop\n')
    assert 'keep: saved' in keep(setup,'save',PI_HOST='')
