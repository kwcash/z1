#!/usr/bin/env bash
# Refresh z1_master.db from a new Fed Z.1 zip, safely.
#   cd /root/z1 && bash update.sh [path/to/new_zip]     (default: /root/z1/z1_csv_files.zip)
#   FORCE=1 bash update.sh new.zip                      (skip the "data shrank" guard)
#
# Builds a scratch database first, checks it, backs up the live one, then swaps and restarts.
# If any check fails the live database and service are left untouched.
set -euo pipefail

cd /root/z1
ZIP="${1:-/root/z1/z1_csv_files.zip}"
DB=z1_master.db
NEW=z1_new.db
KEEP=3   # backups to keep

[ -f "$ZIP" ] || { echo "Missing $ZIP"; exit 1; }
unzip -tq "$ZIP" >/dev/null || { echo "$ZIP is not a valid zip"; exit 1; }

q() { sqlite3 "$1" "$2"; }
cleanup_new() { rm -f "$NEW" "$NEW-wal" "$NEW-shm"; }

echo "== 1/5 build $NEW from $ZIP"
cleanup_new
./venv/bin/python ingest.py --zip "$ZIP" --db "$NEW"
q "$NEW" "PRAGMA wal_checkpoint(TRUNCATE);" >/dev/null

echo "== 2/5 compare with the live database"
[ "$(q "$NEW" "PRAGMA integrity_check;")" = "ok" ] || { echo "integrity check failed"; cleanup_new; exit 1; }
new_series=$(q "$NEW" "SELECT count(*) FROM series")
new_obs=$(q "$NEW" "SELECT count(*) FROM observation")
new_last=$(q "$NEW" "SELECT max(period) FROM observation WHERE series_id='FL152090005.Q'")
old_series=0; old_obs=0; old_last="-"
if [ -f "$DB" ]; then
    old_series=$(q "$DB" "SELECT count(*) FROM series")
    old_obs=$(q "$DB" "SELECT count(*) FROM observation")
    old_last=$(q "$DB" "SELECT max(period) FROM observation WHERE series_id='FL152090005.Q'")
fi
printf '%-22s %12s %12s\n' "" "live" "new"
printf '%-22s %12s %12s\n' "series" "$old_series" "$new_series"
printf '%-22s %12s %12s\n' "observations" "$old_obs" "$new_obs"
printf '%-22s %12s %12s\n' "latest household NW" "$old_last" "$new_last"

if [ "${FORCE:-0}" != 1 ] && { [ $((new_obs * 100)) -lt $((old_obs * 95)) ] || [ $((new_series * 100)) -lt $((old_series * 95)) ]; }; then
    echo "ABORT: new data is more than 5% smaller than live data (wrong or partial zip?)."
    echo "Live database untouched. Re-run with FORCE=1 if this is intended."
    cleanup_new
    exit 1
fi

echo "== 3/5 back up the live database"
if [ -f "$DB" ]; then
    bak="$DB.bak-$(date +%Y%m%d-%H%M%S)"
    q "$DB" ".backup '$bak'"
    echo "saved $bak"
    ls -1t "$DB".bak-* 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
else
    echo "no live database yet, nothing to back up"
fi

echo "== 4/5 swap in the new database and restart"
systemctl stop z1-api
rm -f "$DB-wal" "$DB-shm"   # a stale WAL from the old file must never meet the new one
mv "$NEW" "$DB"
systemctl start z1-api

echo "== 5/5 smoke test"
curl -fsS --retry 10 --retry-connrefused --retry-delay 1 http://127.0.0.1:8000/api/health
echo
echo "Done. To roll back: systemctl stop z1-api; cp $DB.bak-<timestamp> $DB; systemctl start z1-api"
