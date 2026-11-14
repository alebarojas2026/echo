#!/usr/bin/env bash
# Build the screen on a laptop and copy it to the board's web/dist, through the Pi.
#
#   board/push-web.sh
#
# Run it from a clone at the same commit the board is deployed at. It builds
# web/ here (npm ci only when package-lock.json changed), stamps
# web/dist/build.txt with the commit, streams the files over ssh, and swaps
# them in on the board in one move, so serve.py never serves half a build.
# Then it closes the Pi's kiosk browser, which reopens on the new build.
#
# Why build here and not on the board: the board has no internet once it's on
# the hotspot, so npm ci can't run there when dependencies change. Building
# there would also need a current Node.js installed on the board, and the CPU
# and memory the brain and the narrator's model are using. A laptop already
# has Node and node_modules, and copying static files only needs ssh.
#
# Settings come from .env at the repo root (or the environment, which wins):
#   BOARD_USER=...         login on the board
#   BOARD_REPO=/home/...   absolute path of the clone on the board
#   PI_USER=...            login on the Pi
#   PI_HOST=...            how this laptop reaches the Pi
#   BOARD_HOST=192.168.77.2   (default) the board, as the Pi sees it
# Leave PI_HOST empty if this laptop can reach the board directly.

set -euo pipefail

die() { echo "push-web: $*" >&2; exit 1; }
say() { echo "push-web: $*"; }

repo=$(cd "$(dirname "$0")/.." && pwd)
cd "$repo"

# Read one KEY=value from .env without running it as shell.
env_get() {
    [ -f .env ] || return 0
    tr -d '\r' < .env \
        | sed -n -E "s/^[[:space:]]*(export[[:space:]]+)?$1[[:space:]]*=[[:space:]]*//p" \
        | tail -n 1 \
        | sed -E -e 's/[[:space:]]+$//' -e "s/^\"(.*)\"$/\\1/" -e "s/^'(.*)'$/\\1/"
}

setting() {
    local value=${!1:-}
    [ -n "$value" ] || value=$(env_get "$1")
    printf '%s' "$value"
}

main() {
    local board_user board_repo board_host pi_user pi_host
    board_user=$(setting BOARD_USER)
    board_repo=$(setting BOARD_REPO)
    board_host=$(setting BOARD_HOST)
    board_host=${board_host:-192.168.77.2}
    pi_user=$(setting PI_USER)
    pi_host=$(setting PI_HOST)

    [ -n "$board_user" ] || die "set BOARD_USER in .env"
    [ -n "$board_repo" ] || die "set BOARD_REPO in .env (the clone's absolute path on the board)"
    [[ $board_repo =~ ^/[A-Za-z0-9._/-]+$ ]] || die "BOARD_REPO must be an absolute path of letters, digits and . _ - /"
    if [ -n "$pi_host" ] && [ -z "$pi_user" ]; then die "set PI_USER in .env"; fi

    local sha; sha=$(git rev-parse HEAD)
    if [ -n "$(git status --porcelain -- web)" ]; then
        sha="$sha-dirty"
        say "web/ has uncommitted changes; the board will report this build as stale"
    fi

    if [ ! -d web/node_modules ] || [ web/package-lock.json -nt web/node_modules/.package-lock.json ]; then
        (cd web && npm ci)
    fi
    (cd web && npm run build)
    [ -f web/dist/index.html ] || die "the build made no web/dist/index.html"
    echo "$sha" > web/dist/build.txt

    local ssh_board=(ssh)
    [ -z "$pi_host" ] || ssh_board+=(-J "$pi_user@$pi_host")
    ssh_board+=("$board_user@$board_host")

    local swap="set -e
cd '$board_repo/web'
rm -rf dist.new dist.old
mkdir dist.new
tar -xf - -C dist.new
[ -f dist.new/index.html ] || { echo 'no index.html arrived' >&2; exit 1; }
if [ -d dist ]; then mv dist dist.old; fi
mv dist.new dist
rm -rf dist.old
cat dist/build.txt"

    say "copying web/dist to $board_user@$board_host:$board_repo/web/dist${pi_host:+ through $pi_host}"
    local live; live=$(tar -C web/dist -cf - . | "${ssh_board[@]}" "$swap") || die "copy failed; the board still has its previous build"
    [ "$live" = "$sha" ] || die "the board reports build $live, expected $sha"
    say "board is serving build $sha"

    if [ -n "$pi_host" ]; then
        # [k] keeps pkill from matching the remote shell that runs it.
        if ssh "$pi_user@$pi_host" "pkill -f 'user-data-dir=.*radio-sight-kios[k]'"; then
            say "kiosk reopening on the new build"
        else
            say "kiosk not running on the Pi (or not yours); reload it by hand"
        fi
    fi
}

main "$@"; exit $?
