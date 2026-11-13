#!/usr/bin/env bash
# Monthly integrity check of the NAS volume, run from the laptop.
#   nas-check.sh start   btrfs scrub (checksums), then RAID check (both disks equal)
#   nas-check.sh status  progress and results
# Runs on the NAS detached from SSH, so the laptop can be closed after "start".
# Needs SSH on and the NAS sudo password.
set -euo pipefail
NAS=${NAS:?set NAS=user@nas-address, e.g. NAS=me@192.168.1.14}
VOL=/volume1
MD=md1          # data array (RAID 1 today; same name after the RAID 5 migration)

case "${1:-}" in
start)
    # -B waits for the scrub, so the RAID check starts only after it (together they slow each other)
    # sudo -v asks the password in the foreground; the background sudo -n then reuses it
    ssh -t "$NAS" "sudo -v && sudo -n nohup sh -c 'btrfs scrub start -B $VOL; echo check > /sys/block/$MD/md/sync_action' \
        >/dev/null 2>&1 & sleep 2; sudo btrfs scrub status $VOL | grep -E 'Status|Total'"
    echo "Started: scrub first (~1 h), then the RAID check (a few hours). Check with: $0 status"
    ;;
status)
    ssh -t "$NAS" "sudo btrfs scrub status $VOL | grep -E 'started|Status|Duration|Error summary'
        echo
        echo \"RAID: \$(cat /sys/block/$MD/md/sync_action), progress \$(cat /sys/block/$MD/md/sync_completed), mismatches \$(cat /sys/block/$MD/md/mismatch_cnt)\"
        grep -A2 '^$MD' /proc/mdstat"
    echo
    echo "Good: scrub 'finished' + 'no errors found'; RAID 'idle' + mismatches 0 (after the check, not before)."
    ;;
*)
    echo "usage: $0 start|status" >&2
    exit 1
    ;;
esac
