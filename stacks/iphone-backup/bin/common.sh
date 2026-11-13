# Shared helpers for the iphone-* scripts (sourced, not executed).

BACKUP_ROOT=/backup              # bind mount of the personal backup folder
STATE=/data                      # pairing records, UDID, status, log
UDID_FILE=$STATE/udid
STATUS_FILE=$STATE/status.json
LOG_FILE=$STATE/backup.log
PUID=${PUID:-1000}
PGID=${PGID:-10}

log() { echo "$(date '+%F %T') $*" | tee -a "$LOG_FILE"; }

# Push a phone notification through ntfy, if configured
notify() {  # notify <title> <message> [priority]
    [ -n "${NTFY_URL:-}" ] || return 0
    curl -fsS -m 10 -H "Title: $1" -H "Priority: ${3:-default}" -H "Tags: iphone" \
        -d "$2" "$NTFY_URL" >/dev/null || log "ntfy failed"
}

udid() { cat "$UDID_FILE" 2>/dev/null; }

# Run a command as the NAS user so backup files belong to them, not root
as_user() { setpriv --reuid="$PUID" --regid="$PGID" --clear-groups env HOME=/tmp "$@"; }

# Is the paired iPhone visible right now? $1 = -n (network) or -l (USB)
visible() { idevice_id "$1" 2>/dev/null | grep -qx "$(udid)"; }

# Write a small status file (other dashboards can read it later)
write_status() {  # write_status <result> <message>
    local last_ok
    last_ok=$(cat "$STATE/last_success" 2>/dev/null || echo 0)
    printf '{"result":"%s","message":"%s","checked":%s,"last_success":%s,"size":"%s"}\n' \
        "$1" "$2" "$(date +%s)" "$last_ok" \
        "$(du -sh "$BACKUP_ROOT/$(udid)" 2>/dev/null | cut -f1)" > "$STATUS_FILE"
}
