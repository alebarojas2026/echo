import io
import os
import subprocess
import tarfile

import pytest

from ci import trees


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A repo whose main has a.txt and b.txt, and PR refs 1-3: 1 and 2 both change a.txt, 3 adds c.txt."""
    for k, v in {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(tmp_path),
    }.items():
        monkeypatch.setenv(k, v)
    r = tmp_path / "r"
    r.mkdir()

    def run(*args):
        subprocess.run(["git", "-C", str(r), *args], check=True, capture_output=True)

    def commit(files, msg):
        for name, text in files.items():
            (r / name).write_text(text, encoding="utf-8", newline="\n")
        run("add", *files)
        run("commit", "-q", "-m", msg)

    run("init", "-q", "-b", "main")
    run("config", "core.autocrlf", "false")
    commit({"a.txt": "one\n", "b.txt": "b\n"}, "base")
    run("update-ref", "refs/remotes/origin/main", "HEAD")
    for pr, files in ((1, {"a.txt": "from one\n"}), (2, {"a.txt": "from two\n"}), (3, {"c.txt": "c\n"})):
        run("checkout", "-q", "-b", f"pr{pr}", "main")
        commit(files, f"pr {pr}")
        run("update-ref", trees.pr_ref(pr), "HEAD")
    run("checkout", "-q", "main")
    return r


def main_sha(repo):
    return trees.out(repo, "rev-parse", "refs/remotes/origin/main")


def names_in(blob):
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        return sorted(m.name for m in tar.getmembers() if m.isfile())


def test_each_pr_merges_into_main_alone(repo):
    each = trees.each_trees(repo, main_sha(repo), [1, 2, 3])
    assert [t.runnable for t in each] == [True, True, True]
    assert names_in(trees.tarball(repo, each[2].commit)) == ["a.txt", "b.txt", "c.txt"]
    assert trees.show(repo, each[0].commit, "a.txt") == "from one\n"


def test_a_conflict_is_reported_with_its_files(repo):
    m = trees.merge(repo, trees.each_trees(repo, main_sha(repo), [1])[0].commit, trees.pr_ref(2), "x")
    assert m.commit is None
    assert m.conflicts == ["a.txt"]


def test_stack_leaves_out_the_pr_that_conflicts_and_keeps_going(repo):
    t = trees.stack_tree(repo, main_sha(repo), [1, 2, 3])
    assert t.prs == [1, 3]
    assert t.skipped == [(2, ["a.txt"])]
    assert names_in(trees.tarball(repo, t.commit)) == ["a.txt", "b.txt", "c.txt"]
    assert trees.show(repo, t.commit, "a.txt") == "from one\n"


def test_stack_order_decides_who_wins(repo):
    t = trees.stack_tree(repo, main_sha(repo), [2, 1])
    assert t.prs == [2] and t.skipped == [(1, ["a.txt"])]


def test_pair_conflicts(repo):
    assert trees.pair_conflicts(repo, main_sha(repo), [1, 2, 3]) == [(1, 2, ["a.txt"])]


def test_tarball_holds_tracked_files_only(repo):
    (repo / "untracked.txt").write_text("x", encoding="utf-8")
    assert names_in(trees.tarball(repo, main_sha(repo))) == ["a.txt", "b.txt"]
    assert "untracked.txt" not in trees.paths(repo, main_sha(repo))
    assert os.path.exists(repo / "untracked.txt")
