# ci: every lane's tests on the board's Linux and Python, from one command

A development tool. GitHub Actions is down, and we test on Windows with whatever Python we
have, while the board runs Debian 13 with Python 3.13. This runs every lane's tests there, in
parallel, on Modal, and prints one table. Nothing in the demo uses it, the board never sees it,
and it never posts anything to GitHub.

## The one command

```
python ci/modal_ci.py --prs 476,478,485 [--each | --together] [--main]
```

- `--each` (the default): each PR merged into current `origin/main` on its own.
- `--together`: all the PRs stacked on main in the order given. A PR that conflicts with the
  stack so far is left out (and named), and the rest keep stacking. It also lists every pair
  of PRs that conflict with each other, which is what decides a merge order.
- `--main`: main alone. With `--each`, a PR failure that also fails on main is marked "same as main".
- PRs that are no longer open (merged or closed) are skipped and named; it asks `gh` for the open list, read-only.
- `--dry-run` builds the trees and prints the plan without starting anything.
- `--lanes brain,web` runs only those lanes. `--max-dollars` (default 2) refuses a run whose estimate is higher.

Run it with a Python that has `modal` installed and a Modal login. Merges happen on this PC
with git (`git merge-tree`, the same merge `git merge` does, nothing checked out). A merge
conflict is reported with its files and not run. Only each tree's tracked files go up, as a
tarball; no GitHub login leaves the PC.

## What runs

- Image: `debian:trixie-slim`, its Python 3.13, every `requirements*.txt` on main installed in
  a cached layer, and Node 22.
- One container per (tree, lane): 2 CPUs, 10 minutes at most.
- A lane is any top-level folder with a `test_*.py` file (new folders are picked up on their
  own), plus `contracts`, plus `web`:
  - Python lanes: `pip install -r <lane>/requirements.txt`, then `python -m pytest <lane>`.
  - contracts also runs `python -m contracts.check contracts/fixtures/valid*`.
  - web: `npm ci`, the package's typecheck script, `npx vitest run`, `npx vite build`.

## Output

A Markdown table (tree, lane, pass/fail, counts, seconds, first failing tests) on stdout and in
`ci-out/<short-sha>.md` (a run of several trees is named `<main sha>-each` or `-together`). The
full output of every lane is in `ci-out/<name>/`. `ci-out/` is git-ignored.

## Its own tests

`python -m pytest ci` covers lane discovery, conflict reporting and the table, with no Modal
and no network.
