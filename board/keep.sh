#!/usr/bin/env bash
# Save the board's learned state to this laptop, or restore a saved copy over Ethernet.
set -euo pipefail
umask 077
repo=$(cd "$(dirname "$0")/.." && pwd)
cd "$repo"
die() { echo "keep: $*" >&2; exit 1; }
setting() {
    if declare -p "$1" >/dev/null 2>&1; then printf '%s' "${!1}"; return; fi
    local value=${!1:-}
    if [ -z "$value" ] && [ -f .env ]; then
        value=$(tr -d '\r' < .env | sed -n -E "s/^[[:space:]]*(export[[:space:]]+)?$1[[:space:]]*=[[:space:]]*//p" | tail -n 1 | sed -E -e 's/[[:space:]]+$//' -e "s/^\"(.*)\"$/\\1/" -e "s/^'(.*)'$/\\1/")
    fi
    printf '%s' "$value"
}
action=${1:-}
case $action in
    save) [ "$#" -eq 1 ] || die "usage: board/keep.sh save | restore <folder>" ;;
    restore) [ "$#" -eq 2 ] || die "usage: board/keep.sh restore <folder>" ;;
    *) die "usage: board/keep.sh save | restore <folder>" ;;
esac
user=$(setting BOARD_USER)
board_repo=$(setting BOARD_REPO)
host=$(setting BOARD_HOST); host=${host:-192.168.77.2}
[[ $user =~ ^[A-Za-z_][A-Za-z0-9_-]*$ ]] || die "set BOARD_USER to the checkout owner's login"
[[ $board_repo =~ ^/[A-Za-z0-9._/-]+$ ]] || die "BOARD_REPO must be an absolute path without spaces"
[ "$host" = 192.168.77.2 ] || die "use the board's Ethernet address 192.168.77.2, never a hotspot address"
[ -z "$(setting PI_HOST)" ] || die "use a direct Ethernet connection, without PI_HOST"

# Verify the laptop's route as well: the Ethernet destination can be routed over Wi-Fi.
if command -v ip >/dev/null 2>&1; then
    iface=$(ip -o route get "$host" | awk '{for(i=1;i<NF;i++)if($i=="dev"){print $(i+1);exit}}')
    [ -n "$iface" ] || die "cannot determine the Ethernet route"
    [ ! -d "/sys/class/net/$iface/wireless" ] && [ ! -e "/sys/class/net/$iface/phy80211" ] || die "route uses Wi-Fi"
    case $iface in wl*|wlan*) die "route uses Wi-Fi" ;; esac
elif command -v networksetup >/dev/null 2>&1; then
    iface=$(route -n get "$host" | awk '$1=="interface:"{print $2}')
    [ -n "$iface" ] || die "cannot determine the Ethernet route"
    wireless=$(networksetup -listallhardwareports | awk '/^Hardware Port:/{wifi=($0 ~ /Wi-Fi|AirPort/)} /^Device:/ && wifi{print $2}')
    if grep -qx "$iface" <<< "$wireless"; then die "route uses Wi-Fi"; fi
else
    die "cannot verify a wired route on this laptop"
fi
expected=$(setting KEEP_INTERFACE)
[ -z "$expected" ] || [ "$iface" = "$expected" ] || die "route does not use KEEP_INTERFACE"
target="$user@$host"
files=(model.pkl baseline.json place.json baselines.jsonl store.db COMMIT CHECKSUMS)

if [ "$action" = save ]; then
    mkdir -p data/keep
    if ! git check-ignore -q data/keep/check; then
        [ ! -e data/keep/.gitignore ] || die "data/keep is not gitignored"
        printf '*\n' > data/keep/.gitignore
        git check-ignore -q data/keep/check || die "data/keep must be gitignored"
    fi
    stage=$(mktemp -d "$repo/data/keep/.saving.XXXXXX")
    trap 'rm -rf "$stage"' EXIT
    save_script=$(cat <<'REMOTE'
set -eu
cd "$KEEP_REPO/data/sessions"
owner=$(stat -c %u "$KEEP_REPO" 2>/dev/null || stat -f %u "$KEEP_REPO")
[ "$(id -u)" = "$owner" ] || { echo 'keep: connect as the checkout owner' >&2; exit 1; }
for file in model.pkl baseline.json place.json baselines.jsonl store.db; do
    [ -f "$file" ] || { echo "keep: missing $file" >&2; exit 1; }
done
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
before=$(cksum model.pkl baseline.json place.json baselines.jsonl)
cp -p model.pkl baseline.json place.json baselines.jsonl "$stage/"
"${PYTHON:-/opt/rs/venv/bin/python}" -c 'import sqlite3,sys
with sqlite3.connect("file:store.db?mode=ro",uri=True) as source, sqlite3.connect(sys.argv[1]) as target:
    source.backup(target)' "$stage/store.db"
[ "$before" = "$(cksum model.pkl baseline.json place.json baselines.jsonl)" ] || { echo 'keep: learning changed during save; retry after the lesson' >&2; exit 1; }
git -c safe.directory="$KEEP_REPO" -C "$KEEP_REPO" rev-parse HEAD > "$stage/COMMIT"
cd "$stage"
cksum model.pkl baseline.json place.json baselines.jsonl store.db > CHECKSUMS
tar -cf - model.pkl baseline.json place.json baselines.jsonl store.db COMMIT CHECKSUMS
REMOTE
)
    ssh -o ProxyJump=none -o ProxyCommand=none "$target" "KEEP_REPO='$board_repo'
$save_script" | tar -xf - -C "$stage" "${files[@]}"
    (cd "$stage" && cksum model.pkl baseline.json place.json baselines.jsonl store.db | cmp -s - CHECKSUMS) || die "snapshot checksum mismatch"
    saved="$repo/data/keep/$(date -u +%Y%m%dT%H%M%SZ)-$$"
    mv "$stage" "$saved"
    echo "keep: saved $saved (commit $(cat "$saved/COMMIT"))"
    exit 0
fi

folder=$(cd "$2" && pwd)
for file in "${files[@]}"; do [ -f "$folder/$file" ] || die "backup is missing $file"; done
(cd "$folder" && cksum model.pkl baseline.json place.json baselines.jsonl store.db | cmp -s - CHECKSUMS) || die "backup checksum mismatch"
restore_script=$(cat <<'REMOTE'
set -eu
umask 077
cd "$KEEP_REPO"
owner=$(stat -c %u . 2>/dev/null || stat -f %u .)
[ "$(id -u)" = "$owner" ] || { echo 'keep: connect as the checkout owner' >&2; exit 1; }
mkdir -p data/sessions
stage=$(mktemp -d "$KEEP_REPO/data/sessions/.restoring.XXXXXX")
stopped=0
cleanup() {
    result=$?
    rm -rf "$stage"
    if [ "$stopped" = 1 ]; then echo 'keep: restore incomplete; verify brain/store services before retrying' >&2; fi
    exit "$result"
}
trap cleanup EXIT
tar -xf - -C "$stage" model.pkl baseline.json place.json baselines.jsonl store.db COMMIT CHECKSUMS
for file in model.pkl baseline.json place.json baselines.jsonl store.db COMMIT CHECKSUMS; do [ -f "$stage/$file" ]; done
(cd "$stage" && cksum model.pkl baseline.json place.json baselines.jsonl store.db | cmp -s - CHECKSUMS)
[ "$(cat "$stage/COMMIT")" = "$(git -c safe.directory="$KEEP_REPO" rev-parse HEAD)" ] || { echo 'keep: deploy the backup COMMIT before restoring its learned state' >&2; exit 1; }
stopped=1
sudo -n systemctl stop radio-sight-brain.service radio-sight-store.service
rm -f data/sessions/store.db-wal data/sessions/store.db-shm
for file in model.pkl baseline.json place.json baselines.jsonl store.db; do mv "$stage/$file" "data/sessions/$file"; done
sudo -n systemctl start radio-sight-brain.service radio-sight-store.service
stopped=0
"${PYTHON:-/opt/rs/venv/bin/python}" -c 'import socket,subprocess,sys,time
deadline=time.monotonic()+20
while time.monotonic()<deadline:
    ready=True
    for unit in ("radio-sight-brain.service","radio-sight-store.service"):
        try:
            if subprocess.run(["systemctl","is-active","--quiet",unit],timeout=1).returncode: ready=False
        except subprocess.TimeoutExpired: ready=False
    for port in (8080,8765):
        try:
            with socket.create_connection(("127.0.0.1",port),timeout=0.25): pass
        except OSError: ready=False
    if ready: break
    time.sleep(0.25)
else:
    sys.exit("keep: restored services did not become ready within 20 s")' keep-ready
"${PYTHON:-/opt/rs/venv/bin/python}" scripts/demo_check.py --http http://127.0.0.1:8080 --ws ws://127.0.0.1:8765/ws
echo 'keep: restored learned state and checked the demo path'
REMOTE
)
tar -C "$folder" -cf - "${files[@]}" | ssh -o ProxyJump=none -o ProxyCommand=none "$target" "KEEP_REPO='$board_repo'
$restore_script"
