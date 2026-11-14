#!/usr/bin/env bash
# Count the bytes the board sends anywhere other than our two networks and loopback.
#
#   sudo board/egress.sh start    # zero the counters and start counting
#   sudo board/egress.sh          # print bytes out since start: the bytes_out in proof.json
#   sudo board/egress.sh stop     # print the count one last time and stop counting
#
# The counters sit in nftables' postrouting hook, so they see traffic from host
# processes and from App Lab's containers as it leaves the board. Not counted:
# 192.168.77.0/24 (Ethernet to the Pi), 10.42.0.0/24 (the sensing hotspot),
# loopback, and traffic between the board and its own containers (docker*, br-*
# and veth* interfaces never leave the board).
#
# Everything else is counted, and stdout is that strict total. stderr splits it
# into link-local traffic (mDNS, broadcast, IPv6 neighbour discovery: it can't
# pass a router, so it stays on the link it was sent on) and the rest, so a
# nonzero number says what to switch off. The counters live in the kernel; a
# reboot clears them.

set -euo pipefail

NFT=${NFT:-nft}
FAMILY=inet
TABLE=radio_sight_egress

die() { echo "egress: $*" >&2; exit 1; }

ruleset() {
    local t="$FAMILY $TABLE"
    cat <<EOF
add table $t
delete table $t
add table $t
add counter $t link_local
add counter $t other
add chain $t postrouting { type filter hook postrouting priority 0; policy accept; }
add rule $t postrouting oifname "lo" return
add rule $t postrouting oifname "docker*" return
add rule $t postrouting oifname "br-*" return
add rule $t postrouting oifname "veth*" return
add rule $t postrouting ip daddr { 127.0.0.0/8, 192.168.77.0/24, 10.42.0.0/24 } return
add rule $t postrouting ip6 daddr ::1 return
add rule $t postrouting ip daddr { 224.0.0.0/24, 255.255.255.255 } counter name "link_local" return
add rule $t postrouting ip6 daddr { fe80::/10, ff02::/16 } counter name "link_local" return
add rule $t postrouting counter name "other"
EOF
}

counter_bytes() {
    local out
    out=$($NFT list counter $FAMILY $TABLE "$1") || return 1
    awk '{ for (i = 1; i < NF; i++) if ($i == "bytes") { print $(i + 1); exit } }' <<< "$out"
}

count() {
    local link other
    link=$(counter_bytes link_local 2>/dev/null) && other=$(counter_bytes other 2>/dev/null) \
        || die "not counting (or not root): run 'sudo board/egress.sh start' first"
    [[ $link =~ ^[0-9]+$ && $other =~ ^[0-9]+$ ]] || die "couldn't read the counters from nft"
    echo "egress: $((link + other)) bytes out ($link link-local, $other other)" >&2
    echo $((link + other))
}

main() {
    case ${1:-count} in
        start)
            ruleset | $NFT -f - || die "nft failed (run as root?)"
            echo "egress: counting from 0" >&2
            ;;
        count)
            count
            ;;
        stop)
            count
            $NFT delete table $FAMILY $TABLE
            ;;
        *)
            echo "usage: board/egress.sh [start|count|stop]" >&2
            exit 2
            ;;
    esac
}

main "$@"
