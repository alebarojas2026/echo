#!/usr/bin/env bash
# Deploy a tag or commit on the board or the Pi and restart only what changed.
#
#   board/deploy.sh v0.3        # or a sha
#
# Run it as the user who owns the repo clone (it calls sudo for systemctl).
# It refuses to run over uncommitted changes, checks out the ref (detached),
# installs board/units/*.service for this machine with the placeholders filled
# in, and restarts a service only when its unit file or one of the folders it
# runs from changed. A first deploy installs, enables and starts everything.
#
# @REPO@ becomes this clone, @USER@ its owner, and @PYTHON@ .venv/bin/python
# when it exists (python3 otherwise). The llama-server unit is owned by the
# narrator and lives at narrator/llm.service; it's installed as
# radio-sight-llm.service. The Pi hotspot (pi/ap.sh, a NetworkManager profile
# that comes up by itself) and the kiosk (board/kiosk-notes.md, started by the
# desktop session) are not systemd services.
#
# Settings, all optional: ROLE=board|pi (found from the device tree otherwise),
# UNIT_DIR (/etc/systemd/system), SYSTEMCTL (systemctl), SUDO (sudo, or empty).

set -euo pipefail

# unit name               role   unit file                       runs from (folders end in /)
UNITS='
radio-sight-bus           board  board/units/radio-sight-bus.service        bus/ contracts/
radio-sight-wifi-rssi     board  board/units/radio-sight-wifi-rssi.service  radio/ contracts/
radio-sight-hci-scan      board  board/units/radio-sight-hci-scan.service   radio/ contracts/
radio-sight-camwatch      board  board/units/radio-sight-camwatch.service   teacher/ contracts/
radio-sight-brain         board  board/units/radio-sight-brain.service      brain/ advisor/ radio/nodes.json contracts/
radio-sight-serve         board  board/units/radio-sight-serve.service      board/serve.py
radio-sight-llm           board  narrator/llm.service                       narrator/llm.service
radio-sight-narrate       board  board/units/radio-sight-narrate.service    narrator/ contracts/
radio-sight-radio-node    pi     board/units/radio-sight-radio-node.service pi/ radio/ contracts/
'

die() { echo "deploy: $*" >&2; exit 1; }
say() { echo "deploy: $*"; }

detect_role() {
    if grep -qs "Raspberry Pi" /sys/firmware/devicetree/base/model; then echo pi; else echo board; fi
}

# True when a changed path falls under one of the watched folders or files.
touches() {
    local changed=$1; shift
    local path watch
    while IFS= read -r path; do
        [ -n "$path" ] || continue
        for watch in "$@"; do
            case $watch in
                */) [[ $path == "$watch"* ]] && return 0 ;;
                *) [[ $path == "$watch" ]] && return 0 ;;
            esac
        done
    done <<< "$changed"
    return 1
}

main() {
    [ $# -eq 1 ] || die "usage: board/deploy.sh <tag|sha>"
    local ref=$1
    local repo; repo=$(cd "$(dirname "$0")/.." && pwd)
    cd "$repo"

    local role=${ROLE:-$(detect_role)}
    local unit_dir=${UNIT_DIR:-/etc/systemd/system}
    local systemctl=${SYSTEMCTL:-systemctl}
    local sudo
    if [ "$(id -u)" -eq 0 ]; then sudo=""; else sudo=${SUDO-sudo}; fi
    local user; user=$(stat -c %U "$repo")
    local python=python3
    [ -x "$repo/.venv/bin/python" ] && python="$repo/.venv/bin/python"
    [ "$python" = python3 ] && python=$(command -v python3 || echo /usr/bin/python3)

    git diff --quiet && git diff --cached --quiet || die "uncommitted changes in $repo; commit or stash them first"
    timeout 30 git fetch --quiet --tags origin 2>/dev/null || say "fetch failed (no network?); using refs already here"
    local new; new=$(git rev-parse --verify --quiet "$ref^{commit}") || die "unknown tag or sha: $ref"
    local old; old=$(git rev-parse HEAD)
    git checkout --quiet --detach "$new"
    local changed; changed=$(git diff --name-only "$old" "$new")
    say "$role at ${new:0:8} ($ref), was ${old:0:8}; $(grep -c . <<< "$changed" || true) files changed"

    tmp=$(mktemp)
    trap 'rm -f "$tmp"' EXIT
    local reload=0 enable=() restart=()
    local name unit_role src watch
    while read -r name unit_role src watch; do
        [ -n "$name" ] && [ "$unit_role" = "$role" ] || continue
        if [ ! -f "$src" ]; then
            say "skipping $name: $src doesn't exist yet"
            continue
        fi
        sed -e "s|@REPO@|$repo|g" -e "s|@USER@|$user|g" -e "s|@PYTHON@|$python|g" "$src" > "$tmp"
        local target="$unit_dir/$name.service"
        if ! cmp -s "$tmp" "$target"; then
            $sudo cp "$tmp" "$target"
            $sudo chmod 644 "$target"
            reload=1
            enable+=("$name.service")
            restart+=("$name.service")
        elif touches "$changed" $watch; then
            restart+=("$name.service")
        fi
    done <<< "$UNITS"

    if [ "$reload" -eq 1 ]; then
        $sudo $systemctl daemon-reload
    fi
    if [ ${#enable[@]} -gt 0 ]; then
        $sudo $systemctl enable --quiet "${enable[@]}"
    fi
    if [ ${#restart[@]} -gt 0 ]; then
        say "restarting ${restart[*]}"
        $sudo $systemctl restart "${restart[@]}"
    else
        say "nothing to restart"
    fi

    if [ "$role" = board ] && touches "$changed" web/; then
        if [ -d web/node_modules ] && command -v npm > /dev/null; then
            say "web/ changed; rebuilding web/dist"
            (cd web && npm run build)
        else
            say "web/ changed but web/node_modules is missing; web/dist is stale until you build it"
        fi
    fi
    local req
    for req in $(grep 'requirements.txt$' <<< "$changed" || true); do
        say "$req changed; run pip install -r $req"
    done
}

# Everything is in functions so a checkout that rewrites this file can't
# change the part still being read.
main "$@"; exit $?
