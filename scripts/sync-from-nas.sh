#!/usr/bin/env bash
# Pull the current stack configs from the NAS into stacks/ (secrets and data excluded).
# Run from the repo root before committing.
set -euo pipefail
NAS=${NAS:?set NAS=user@nas-address, e.g. NAS=me@192.168.1.14}
cd "$(dirname "$0")/.."

# Self-managed stacks in /volume1/docker (only config files, never .env or data/)
ssh "$NAS" 'cd /volume1/docker && find adguard homepage dockge uptime-kuma autobangumi speedtest-tracker glances netwatch minecraft_server tailscale mission-control home \
    -maxdepth 3 -type f \( -name "docker-compose.yaml" -o -name "Dockerfile" -o -name "*.py" \
    -o -path "homepage/config/settings.yaml" -o -path "homepage/config/services.yaml" \
    -o -path "homepage/config/widgets.yaml" -o -path "homepage/config/bookmarks.yaml" \
    -o -path "homepage/config/docker.yaml" -o -path "homepage/config/custom.css" -o -path "netwatch/static/*" \
    -o -name "prometheus.yml" -o -name ".env.example" -o -path "mission-control/web/static/*" \
    -o -path "home/static/*" -o -path "home/feeds.json" \) \
    -not -path "*/data/*" -print0 2>/dev/null | tar --null -T - -cf -' | tar -C stacks -xf -

# UGREEN app-store qBittorrent (compose only)
ssh "$NAS" 'cat /volume1/@appstore/com.ugreen.docker.qbittorrent/docker-compose.yaml' > stacks/qbittorrent/docker-compose.yaml

# The NAS marks everything executable; nothing under stacks/ needs to be
find stacks -type f -perm /111 -exec chmod 644 {} +

# Safety net: refuse to continue if something looks like a secret
# (commented-out lines are ignored)
if grep -rniE '^[^#]*(password|passwd|secret|token|apikey)[[:space:]]*[:=][[:space:]]*[^[:space:]{"]' stacks; then
  echo "Possible secret found above: fix before committing." >&2
  exit 1
fi
git status --short
