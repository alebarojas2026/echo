import pytest
from pathlib import Path

from proof.manual import update, check_routes
from proof.provenance import empty_proof
from proof.render_table import render
from proof.storage import audit, media_files, check_meter, Docker


class FakeDocker:
    def __init__(self, images=0, mounts=()):
        self.images,self.mounts = images,list(mounts)
        self.calls = []

    def request(self,method,path):
        self.calls.append((method,path))
        if path.endswith('/json'): return {"Mounts":self.mounts}
        raise AssertionError('unexpected API request')

    def scan(self,container,exclude):
        self.excluded = exclude
        return self.images


def test_empty_two_and_missing_folder(tmp_path):
    assert audit([tmp_path],"teacher",FakeDocker())["count"] == 0
    # Empty suffix markers exercise the inventory without containing image data.
    (tmp_path/'one.JPG').touch()
    (tmp_path/'two.webm').touch()
    (tmp_path/'states.json').touch()
    result = audit([tmp_path],"teacher",FakeDocker())
    assert result['count'] == 2 and result['folders'] == [str(tmp_path)]
    with pytest.raises(ValueError,match='missing'):
        audit([tmp_path,tmp_path/'missing'],"teacher",FakeDocker())


def test_aliases_mounts_and_symlink_loop_count_once(tmp_path):
    (tmp_path/'one.png').touch()
    (tmp_path/'alias.png').hardlink_to(tmp_path/'one.png')
    try:
        (tmp_path/'loop').symlink_to(tmp_path,target_is_directory=True)
    except OSError as error:
        pytest.skip(f'symlinks unavailable: {error}')
    docker = FakeDocker(mounts=[{'Source':str(tmp_path),'Destination':'/app'}])
    assert audit([tmp_path],"teacher",docker)['count'] == 1
    assert '/app' in docker.excluded
    (tmp_path/'broken').symlink_to(tmp_path/'missing')
    with pytest.raises(ValueError,match='cannot be inspected'): media_files([tmp_path])


def test_full_container_and_library_subfolders_are_counted(tmp_path):
    library = tmp_path/'site-packages'
    library.mkdir()
    (library/'asset.gif').touch()
    docker = FakeDocker(images=2)
    assert audit([tmp_path],"teacher",docker)['count'] == 3
    assert docker.excluded == ['/proc','/sys','/dev']


def test_virtual_mount_is_scanned_in_container_and_special_host_file_is_known(tmp_path):
    if not Path('/dev/null').exists(): pytest.skip('/dev/null is unavailable')
    docker = FakeDocker(images=2,mounts=[{'Type':'tmpfs','Source':'','Destination':'/scratch'},
                                        {'Source':'/dev/null','Destination':'/null'}])
    result = audit([tmp_path],'teacher',docker)
    assert result['count'] == 2 and result['files'] == ['/dev/null']
    assert '/scratch' not in docker.excluded and '/null' in docker.excluded


def test_container_walk_is_read_only_and_stopped_container_fails(monkeypatch):
    import subprocess
    calls = []
    def execute(command,**kwargs):
        calls.append(command)
        compile(command[7],'<container-inventory>','exec')
        return '2\n'
    monkeypatch.setattr('proof.storage.subprocess.check_output',execute)
    assert Docker().scan('teacher',['/app']) == 2
    assert calls[0][:7] == ['docker','exec','--user','0','teacher','python3','-c']
    assert calls[0][-1] == '/app'
    def stopped(*args,**kwargs): raise subprocess.CalledProcessError(1,args[0])
    monkeypatch.setattr('proof.storage.subprocess.check_output',stopped)
    with pytest.raises(ValueError,match='running'): Docker().scan('teacher',[])


def test_docker_and_required_scope_fail_closed(tmp_path):
    with pytest.raises(ValueError,match='select'): audit([tmp_path],None,FakeDocker())
    with pytest.raises(ValueError,match='mounted path'):
        audit([tmp_path],"teacher",FakeDocker(mounts=[{'Source':str(tmp_path/'missing'),'Destination':'/app'}]))
    class Unavailable:
        def request(self,*args): raise ValueError('Docker unavailable')
    with pytest.raises(ValueError,match='unavailable'): audit([tmp_path],"teacher",Unavailable())


def test_meter_comparison_is_explicit_fresh_and_exact():
    assert check_meter(0,lambda:{'ok':True,'images':0,'t':10000},lambda:11) is True
    for value in [{'ok':False},{'ok':True,'images':None,'t':10000},
                  {'ok':True,'images':1,'t':10000},{'ok':True,'images':0,'t':1}]:
        with pytest.raises(ValueError): check_meter(0,lambda:value,lambda:11)


def test_privacy_first_measurement_and_render_own_date(tmp_path):
    captured = audit([tmp_path],"teacher",FakeDocker())
    proof,evidence = update(empty_proof(),'abc1234','2026-11-15T04:00:00Z',image_audit=captured)
    proof['measured_at'] = '2026-11-14T12:00:00Z'
    assert proof['images_stored'] == 0 and proof['zone']['correct'] is None
    template = '| Images stored | __ | audit | __ | __ | __ |'
    output = render(template,proof,evidence=[evidence])
    assert '| 0 |' in output and '1 folders; 0 mounted files; 1 containers' in output
    assert '2026-11-15T04:00:00Z' in output and 'meter and one-off' not in output
    captured['meter_images_agree'] = True
    assert 'meter and one-off audit agree' in render(template,proof,evidence=[evidence])
    stale = dict(evidence,commit='def5678')
    assert '| 0 | audit | __ | __ | abc1234 |' in render(template,proof,evidence=[stale])


def test_egress_row_has_own_interval_and_requires_no_default(monkeypatch):
    proof,evidence = update(empty_proof(),'abc1234','2026-11-15T04:00:00Z',egress='0',
                            egress_source='full rehearsal',egress_duration_s=180)
    evidence['no_default_route'] = True
    result = render('| Bytes sent outside our network | __ | counter | __ | __ | __ |',proof,evidence=[evidence])
    assert '180 s' in result and 'no IPv4 or IPv6 default route' in result
    monkeypatch.setattr('proof.manual.subprocess.check_output',lambda *a,**k:'')
    check_routes()
    monkeypatch.setattr('proof.manual.subprocess.check_output',lambda *a,**k:'default via router')
    with pytest.raises(ValueError,match='default route'): check_routes()


def test_cli_first_audit_is_schema_valid_and_failure_writes_nothing(tmp_path,monkeypatch):
    import json
    from proof.manual import main
    output = tmp_path/'proof.json'
    monkeypatch.setattr('sys.argv',['manual','--proof',str(output),'--images','--teacher-container','teacher',
                                    '--measured-at','2026-11-15T04:00:00Z'])
    monkeypatch.setattr('proof.manual.subprocess.check_output',lambda *a,**k:'abc1234')
    def unavailable(*args): raise ValueError('required audit folder is missing')
    monkeypatch.setattr('proof.manual.capture_images',unavailable)
    with pytest.raises(SystemExit): main()
    assert not output.exists() and not output.with_suffix('.manual.jsonl').exists()
    monkeypatch.setattr('proof.manual.capture_images',lambda *a:audit([tmp_path],'teacher',FakeDocker()))
    main()
    assert json.loads(output.read_text())['images_stored'] == 0
    assert json.loads(output.with_suffix('.manual.jsonl').read_text())['image_audit']['folders'] == [str(tmp_path)]
