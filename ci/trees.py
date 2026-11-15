"""Build the trees to test, with git on this PC: main, each PR merged into main, or a stack.

Merges use `git merge-tree --write-tree`, the same merge `git merge` does, but in git's object
store: nothing is checked out, so no working folder (and no Windows line-ending conversion)
gets between the commit and the tarball.
"""

import subprocess
from dataclasses import dataclass, field


class GitError(RuntimeError):
    pass


def git(repo, *args, check=True):
    proc = subprocess.run(["git", "-C", str(repo), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {proc.stderr.decode('utf-8', 'replace').strip()}")
    return proc


def out(repo, *args):
    return git(repo, *args).stdout.decode("utf-8", "replace").strip()


def pr_ref(pr):
    return f"refs/ci/pr/{pr}"


def fetch(repo, prs, remote="origin"):
    """Fetch main and every PR head into refs/ci/pr/<n>. Uses this PC's own git login."""
    specs = [f"+refs/heads/main:refs/remotes/{remote}/main"] + [f"+refs/pull/{n}/head:{pr_ref(n)}" for n in prs]
    git(repo, "fetch", "--quiet", remote, *specs)


@dataclass
class Merge:
    commit: str | None
    conflicts: list


def merge(repo, base, head, message):
    """Merge `head` into `base`. Returns the merge commit, or None and the conflicting files."""
    proc = git(repo, "merge-tree", "--write-tree", "--name-only", "--no-messages", base, head, check=False)
    lines = proc.stdout.decode("utf-8", "replace").splitlines()
    if proc.returncode == 0:
        commit = out(repo, "commit-tree", lines[0], "-p", base, "-p", head, "-m", message)
        return Merge(commit, [])
    if proc.returncode == 1:
        files = []
        for line in lines[1:]:
            if not line.strip():
                break
            if line not in files:
                files.append(line)
        return Merge(None, files)
    raise GitError(f"git merge-tree {base} {head}: {proc.stderr.decode('utf-8', 'replace').strip()}")


@dataclass
class Tree:
    name: str  # "main", "#491", or "stack"
    commit: str | None
    prs: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)  # files, when this tree could not be built
    skipped: list = field(default_factory=list)  # (pr, files) left out of a stack because they conflicted

    @property
    def runnable(self):
        return self.commit is not None


def main_tree(repo, main):
    return Tree("main", main)


def each_trees(repo, main, prs):
    trees = []
    for pr in prs:
        m = merge(repo, main, pr_ref(pr), f"ci: #{pr} into main")
        trees.append(Tree(f"#{pr}", m.commit, [pr], m.conflicts))
    return trees


def stack_tree(repo, main, prs):
    """Merge the PRs onto main in the given order. A PR that conflicts with the stack so far is
    left out and listed in `skipped`; the rest keep stacking."""
    commit, used, skipped = main, [], []
    for pr in prs:
        m = merge(repo, commit, pr_ref(pr), f"ci: stack #{pr}")
        if m.commit is None:
            skipped.append((pr, m.conflicts))
        else:
            commit = m.commit
            used.append(pr)
    return Tree("stack", commit if used else None, used, [], skipped)


def pair_conflicts(repo, main, prs):
    """Every pair of PRs that merge into main alone but conflict with each other: (a, b, files)."""
    alone = {}
    for pr in prs:
        m = merge(repo, main, pr_ref(pr), f"ci: #{pr} into main")
        if m.commit:
            alone[pr] = m.commit
    pairs = []
    clean = [p for p in prs if p in alone]
    for i, a in enumerate(clean):
        for b in clean[i + 1:]:
            m = merge(repo, alone[a], pr_ref(b), f"ci: #{b} onto #{a}")
            if m.commit is None:
                pairs.append((a, b, m.conflicts))
    return pairs


def paths(repo, commit):
    return out(repo, "ls-tree", "-r", "--name-only", commit).splitlines()


def show(repo, commit, path):
    proc = git(repo, "show", f"{commit}:{path}", check=False)
    return proc.stdout.decode("utf-8", "replace") if proc.returncode == 0 else None


def tarball(repo, commit):
    """The commit's tracked files as a .tar.gz."""
    return git(repo, "archive", "--format=tar.gz", commit).stdout
