import json
import subprocess

import pytest

from ci import modal_ci


def fake_gh(monkeypatch, code=0, rows=()):
    def run(cmd, **kwargs):
        assert cmd[:3] == ["gh", "pr", "list"]  # read-only: nothing is ever posted
        return subprocess.CompletedProcess(cmd, code, json.dumps(list(rows)).encode(), b"")

    monkeypatch.setattr(modal_ci.subprocess, "run", run)


def test_prs_no_longer_open_are_named(monkeypatch):
    fake_gh(monkeypatch, rows=[{"number": 487}, {"number": 495}])
    assert modal_ci.not_open([487, 508, 495, 514]) == [508, 514]


def test_without_gh_nothing_is_skipped(monkeypatch):
    fake_gh(monkeypatch, code=1)
    assert modal_ci.not_open([487]) == []


def test_args_default_to_each_and_need_something_to_test():
    args = modal_ci.parse_args(["--prs", "476, 478"])
    assert args.each and not args.together and args.pr_list == [476, 478]
    assert modal_ci.parse_args(["--main"]).pr_list == []
    with pytest.raises(SystemExit):
        modal_ci.parse_args([])


def test_refs_alone_are_enough():
    args = modal_ci.parse_args(["--refs", "my-fix, other"])
    assert args.ref_list == ["my-fix", "other"] and args.pr_list == []
