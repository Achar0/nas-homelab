#!/usr/bin/env bash
# One-time step on the NAS: move the admin login from admin-auth.env to admin-auth/auth.json,
# keeping the current password. Prints no values. Run it over SSH:
#   ssh <user>@192.168.1.14 'bash -s' < scripts/migrate-admin-auth.sh
set -euo pipefail
umask 077
base=/volume1/docker
out="$base/admin-auth/auth.json"
if [ -e "$out" ]; then
  echo "$out already exists, nothing done" >&2
  exit 1
fi
value() { grep -E "^$1=" "$base/admin-auth.env" | cut -d= -f2-; }
hash_value=$(value ADMIN_PASSWORD_HASH)
key_value=$(value SESSION_SECRET)
if [ -z "$hash_value" ] || [ -z "$key_value" ]; then
  echo "admin-auth.env is missing a value, nothing done" >&2
  exit 1
fi
mkdir -p "$base/admin-auth"
chmod 700 "$base/admin-auth"
printf '{"hash": "%s", "key": "%s"}\n' "$hash_value" "$key_value" > "$out.part"
mv "$out.part" "$out"
echo done
