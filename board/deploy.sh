#!/usr/bin/env bash
# Install the systemd units, or deploy a tag or commit and restart only what changed.
#
#   sudo board/deploy.sh --install [--no-pi]   # install from the current checkout
#   board/deploy.sh <tag|sha> [--no-pi]        # as the clone's owner: check out, then install
#   ... --online                               # undo the quiet step (an install over a phone hotspot)
#
# The quiet step (board only, every run): the board's own services that call out to the internet
# by themselves (time sync, apt's timers, firmware checks; QUIET_UNITS) are stopped and disabled,
# because on the closed network they go nowhere and the privacy meter counts every byte they
# send. The board's clock is set from the laptop instead (POST /clock). What was stopped is
# written to /var/lib/radio-sight/quieted-units; --online starts exactly those again and forgets
# them. Run with --online before installing anything over a phone hotspot, and without it after.
#
# Both are safe to run again. Every run installs this machine's units from
# board/units/ (placeholders filled in, see board/units/README.md), then
# enables and starts every unit in the list below, so a unit that was left off
# comes back. A unit is restarted only when its unit file or a folder it runs
# from changed. --no-pi still installs the units that need the Pi (its hotspot
# and beacons) or the Ethernet link, but stops and disables them instead of
# starting them; run again without it once the Pi is up.
#
# With a ref it refuses to run over uncommitted changes, fetches (carrying on
# offline) and checks the ref out detached. The screen's web/dist is built on
# a laptop and copied over by board/push-web.sh; this only says whether the
# copy on the board matches.
#
# The narrator's llama-server unit lives at narrator/llm.service and is
# installed as radio-sight-llm.service. The Pi hotspot (pi/ap.sh) and the kiosk
# (board/kiosk-notes.md) are not systemd services.
#
# Settings, all optional: PYTHON (/opt/rs/venv/bin/python), ROLE=board|pi|pib
# (board or pi is found from the device tree otherwise; pib, the second Pi of
# the desk layout, has to be given: ROLE=pib, as pi/install.sh does), UNIT_DIR (/etc/systemd/system),
# SYSTEMCTL (systemctl), SUDO (sudo, or empty). Under sudo, pass them as
# `sudo PYTHON=... board/deploy.sh --install`.

set -euo pipefail

USAGE="usage: board/deploy.sh <tag|sha> [--no-pi] [--online]  or  sudo board/deploy.sh --install [--no-pi] [--online]"

# Services that call out to the internet by themselves, quieted on the board (see the top).
QUIET_UNITS='systemd-timesyncd.service chrony.service ntpsec.service ntp.service apt-daily.timer apt-daily-upgrade.timer unattended-upgrades.service fwupd-refresh.timer packagekit.service'

# The units to install and run. needs: - = nothing else, pi = the Pi's hotspot
# or beacons, link = the Ethernet link to the board. The Pi's radio node is -:
# it advertises and scans without the cable and forwards once it's in. Pi B
# (pib) has no cable: its node and its Wi-Fi reader send through Pi A's hotspot,
# and its .env names its node and link (RADIO_NODE, WIFI_LINK, BUS_HOST).
# unit                    role   needs  unit file                                   runs from (folders end in /)
UNITS='
radio-sight-bus           board  -      board/units/radio-sight-bus.service         bus/ radio/nodes.json contracts/
radio-sight-wifi-rssi     board  pi     board/units/radio-sight-wifi-rssi.service   radio/ contracts/
radio-sight-hci-scan      board  pi     board/units/radio-sight-hci-scan.service    radio/ contracts/
radio-sight-camwatch      board  -      board/units/radio-sight-camwatch.service    teacher/ contracts/
radio-sight-brain         board  -      board/units/radio-sight-brain.service       brain/ advisor/ radio/nodes.json contracts/ board/layout.py
radio-sight-serve         board  -      board/units/radio-sight-serve.service       board/serve.py board/layout.py board/privacy.py board/clock.py agent/ store/
radio-sight-store         board  -      board/units/radio-sight-store.service       store/ contracts/
radio-sight-privacy       board  -      board/units/radio-sight-privacy.service     board/privacy.py board/privacy.nft board/privacy-ports.nft
radio-sight-clock         board  -      board/units/radio-sight-clock.service       board/clock.py
radio-sight-llm           board  -      narrator/llm.service                        narrator/llm.service
radio-sight-narrate       board  -      board/units/radio-sight-narrate.service     narrator/ contracts/
radio-sight-radio-node    pi     -      board/units/radio-sight-radio-node.service  pi/ radio/ contracts/
radio-sight-radio-node    pib    -      board/units/radio-sight-radio-node.service  pi/ radio/ contracts/
radio-sight-wifi-rssi     pib    -      board/units/radio-sight-wifi-rssi.service   radio/ contracts/
'

die() { echo "deploy: $*" >&2; exit 1; }
say() { echo "deploy: $*"; }

# Read-only git that also works under sudo in a clone owned by someone else.
g() { git -c safe.directory="$repo" "$@"; }

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

# The quiet step. quiet: stop and disable the QUIET_UNITS that are enabled here, and remember
# them. online: enable and start again exactly the ones remembered.
quiet_board() {
    local mode=$1 state=${QUIET_STATE:-/var/lib/radio-sight/quieted-units}
    local dirs=${QUIET_UNIT_DIRS:-/lib/systemd/system /usr/lib/systemd/system /etc/systemd/system}
    local unit dir found
    if [ "$mode" = online ]; then
        if [ ! -s "$state" ]; then
            say "online: nothing was quieted on this board"
            return 0
        fi
        local back=()
        while IFS= read -r unit; do
            [ -n "$unit" ] || continue
            $sudo $systemctl enable --now --quiet "$unit" && back+=("$unit") || say "couldn't start $unit again"
        done < "$state"
        $sudo rm -f "$state"
        say "online: started again: ${back[*]}; the board may now call out (the privacy meter counts it)"
        return 0
    fi
    local quieted=()
    for unit in $QUIET_UNITS; do
        found=0
        for dir in $dirs; do [ -e "$dir/$unit" ] && found=1; done
        [ "$found" -eq 1 ] || continue
        $systemctl is-enabled --quiet "$unit" 2>/dev/null || continue
        $sudo $systemctl disable --now --quiet "$unit" && quieted+=("$unit")
    done
    if [ ${#quieted[@]} -gt 0 ]; then
        $sudo mkdir -p "$(dirname "$state")"
        printf '%s\n' "${quieted[@]}" | $sudo tee -a "$state" > /dev/null
        say "quiet: stopped ${quieted[*]} (they call out to the internet by themselves; --online undoes it)"
    else
        say "quiet: nothing here calls out by itself any more"
    fi
}

# web/dist isn't built here (see board/push-web.sh for why). Say whether the
# build that's there was made from the same web/ files as this checkout.
check_web() {
    local built
    built=$(cat web/dist/build.txt 2>/dev/null || true)
    if [ -z "$built" ]; then
        say "web/dist has no build.txt; from a laptop at $1, run board/push-web.sh"
    elif [[ $built != *-dirty ]] &&
        [ "$(g rev-parse --quiet --verify "$built^{commit}:web" 2>/dev/null)" = "$(g rev-parse HEAD:web)" ]; then
        say "web/dist is current (built at ${built:0:8})"
    else
        say "web/dist is stale (built at ${built:0:8}); from a laptop at $1, run board/push-web.sh"
    fi
}

main() {
    local ref="" install=0 no_pi=0 network=quiet arg
    for arg in "$@"; do
        case $arg in
            --install) install=1 ;;
            --no-pi) no_pi=1 ;;
            --online) network=online ;;
            -*) die "unknown option $arg; $USAGE" ;;
            *) [ -z "$ref" ] || die "$USAGE"; ref=$arg ;;
        esac
    done
    if { [ "$install" -eq 1 ] && [ -n "$ref" ]; } || { [ "$install" -eq 0 ] && [ -z "$ref" ]; }; then
        die "$USAGE"
    fi

    repo=$(cd "$(dirname "$0")/.." && pwd)
    cd "$repo"
    local role=${ROLE:-$(detect_role)}
    local unit_dir=${UNIT_DIR:-/etc/systemd/system}
    local systemctl=${SYSTEMCTL:-systemctl}
    local user; user=$(stat -c %U "$repo")
    local sudo=${SUDO-sudo}
    if [ "$(id -u)" -eq 0 ]; then
        sudo=""
        if [ -n "$ref" ] && [ "$user" != root ]; then
            die "run 'board/deploy.sh $ref' as $user, without sudo (it uses sudo itself), so the checkout stays $user's"
        fi
    fi
    local python=${PYTHON:-/opt/rs/venv/bin/python}
    [ -x "$python" ] || say "warning: $python isn't there yet; the units can't start until it is (or set PYTHON)"

    local changed="" label
    if [ -n "$ref" ]; then
        git diff --quiet && git diff --cached --quiet || die "uncommitted changes in $repo; commit or stash them first"
        timeout 30 git fetch --quiet --tags origin 2>/dev/null || say "fetch failed (no network?); using refs already here"
        local new; new=$(git rev-parse --verify --quiet "$ref^{commit}") || die "unknown tag or sha: $ref"
        local old; old=$(git rev-parse HEAD)
        git checkout --quiet --detach "$new"
        changed=$(git diff --name-only "$old" "$new")
        say "$role at ${new:0:8} ($ref), was ${old:0:8}; $(grep -c . <<< "$changed" || true) files changed"
        label=$ref
    else
        label=$(g rev-parse --short HEAD)
        say "installing $role units from the checkout at $label"
    fi

    tmp=$(mktemp)
    trap 'rm -f "$tmp"' EXIT
    local reload=0 want=() skip=() restart=()
    local name unit_role needs src watch
    while read -r name unit_role needs src watch; do
        [ -n "$name" ] && [ "$unit_role" = "$role" ] || continue
        if [ ! -f "$src" ]; then
            say "skipping $name: $src doesn't exist yet"
            continue
        fi
        sed -e "s|@REPO@|$repo|g" -e "s|@USER@|$user|g" -e "s|@PYTHON@|$python|g" "$src" > "$tmp"
        local target="$unit_dir/$name.service" fresh=0
        if ! cmp -s "$tmp" "$target"; then
            $sudo cp "$tmp" "$target"
            $sudo chmod 644 "$target"
            reload=1
            fresh=1
        fi
        if [ "$no_pi" -eq 1 ] && [ "$needs" != - ]; then
            skip+=("$name.service")
        else
            want+=("$name.service")
            if [ "$fresh" -eq 1 ] || touches "$changed" $watch; then
                restart+=("$name.service")
            fi
        fi
    done <<< "$UNITS"

    # An older narrator README installed the model server as llm.service; two of
    # them would fight over port 8091.
    if [ "$role" = board ] && grep -qs "Radio Sight narrator model" "$unit_dir/llm.service"; then
        say "removing the old llm.service (now radio-sight-llm.service)"
        $sudo $systemctl disable --now --quiet llm.service || true
        $sudo rm -f "$unit_dir/llm.service"
        reload=1
    fi

    if [ "$reload" -eq 1 ]; then
        $sudo $systemctl daemon-reload
    fi
    if [ ${#skip[@]} -gt 0 ]; then
        say "installed but not running (needs the Pi or the Ethernet link): ${skip[*]}"
        $sudo $systemctl disable --now --quiet "${skip[@]}" || true
    fi
    if [ ${#restart[@]} -gt 0 ]; then
        say "restarting ${restart[*]}"
        $sudo $systemctl restart "${restart[@]}"
    else
        say "nothing to restart"
    fi
    if [ ${#want[@]} -gt 0 ]; then
        # Starts anything that's stopped; leaves running units alone.
        $sudo $systemctl enable --now --quiet "${want[@]}"
        say "enabled and running: ${want[*]}"
    fi

    if [ "$role" = board ]; then
        quiet_board "$network"
        check_web "$label"
    fi
    local req
    for req in $(grep 'requirements.txt$' <<< "$changed" || true); do
        say "$req changed; run pip install -r $req"
    done
}

# Everything is in functions so a checkout that rewrites this file can't
# change the part still being read.
main "$@"; exit $?
