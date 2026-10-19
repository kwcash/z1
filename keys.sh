#!/usr/bin/env bash
# Manage API keys for the Z.1 API (stored hashed in /root/z1/api_keys.txt).
#   bash keys.sh add <name>      create a key (shown once) and enable key checking
#   bash keys.sh list            show key names
#   bash keys.sh revoke <name>   delete a key (the last key cannot be revoked)
# Callers send the key in the X-API-Key header. /api/health stays open.
set -euo pipefail

cd /root/z1
F=api_keys.txt
cmd="${1:-}"
name="${2:-}"

valid_name() {
    [[ "$1" =~ ^[A-Za-z0-9_.-]{1,40}$ ]] || { echo "name: letters, digits, . _ - only (max 40)"; exit 1; }
}
restart() { systemctl restart z1-api && echo "z1-api restarted"; }

case "$cmd" in
add)
    valid_name "$name"
    if [ -f "$F" ] && awk -v n="$name" '$1==n{f=1} END{exit !f}' "$F"; then
        echo "key '$name' already exists (revoke it first)"; exit 1
    fi
    key=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
    hash=$(printf '%s' "$key" | sha256sum | cut -d' ' -f1)
    touch "$F"; chmod 600 "$F"
    echo "$name $hash" >> "$F"
    echo "API key for '$name' (shown once, save it now):"
    echo "$key"
    restart
    ;;
list)
    [ -s "$F" ] && awk '{print $1}' "$F" || echo "no keys: API is open (localhost only)"
    ;;
revoke)
    valid_name "$name"
    [ -f "$F" ] && awk -v n="$name" '$1==n{f=1} END{exit !f}' "$F" || { echo "no key named '$name'"; exit 1; }
    if [ "$(awk -v n="$name" '$1!=n' "$F" | wc -l)" -eq 0 ]; then
        echo "'$name' is the last key. Add a new one first, so the API never ends up open by accident."; exit 1
    fi
    awk -v n="$name" '$1!=n' "$F" > "$F.tmp" && chmod 600 "$F.tmp" && mv "$F.tmp" "$F"
    echo "revoked '$name'"
    restart
    ;;
*)
    echo "usage: bash keys.sh add <name> | list | revoke <name>"; exit 1
    ;;
esac
