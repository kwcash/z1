#!/usr/bin/env bash
# Refresh z1_master.db from a new Fed Z.1 release, safely, and keep the history.
#
# HOW TO USE (about 2 minutes, once a quarter, after the Fed publishes a new Z.1):
#   1. Download the new "Z.1 CSV files" zip from https://www.federalreserve.gov/releases/z1/
#      and put it on the VPS, e.g.   scp FRB_Z1_csv.zip root@<vps>:/root/z1/new_z1.zip
#   2. On the VPS:                    cd /root/z1 && bash update.sh /root/z1/new_z1.zip
#      With no argument it uses /root/z1/z1_csv_files.zip.
#   3. Read the comparison table it prints. It stops by itself if the new data looks wrong.
#
# OPTIONS (environment variables):
#   FORCE=1 bash update.sh new.zip           skip the "new data is >5% smaller" guard
#   REBUILD_SHADOWS=0 bash update.sh ...     don't rebuild the shadow databases afterwards
#
# WHAT IT DOES
#   1. builds z1_new.db from the zip (aborts if two CSV files disagree on any value)
#   2. integrity-checks it and compares size and latest period with the live database
#   3. keeps the zip forever in archive/, and records every value that changed, appeared or
#      disappeared in the new database's `revision` table (old values are never lost)
#   4. backs up the live database (the newest 3 backups are kept)
#   5. stops the API, swaps the new database in (plus its fingerprint), restarts the API
#   6. smoke-tests the API, verifies the fingerprint, rebuilds every shadow database
#
# If any check in steps 1-3 fails, the live database and the API are left untouched.
#
# ROLL BACK:   systemctl stop z1-api; cp z1_master.db.bak-<timestamp> z1_master.db
#              rm -f z1_master.db-wal z1_master.db-shm; python3 shadow.py seal; systemctl start z1-api
#              (the archived zip is in archive/ if you would rather rebuild with setup_vps.sh)
#
# Z1_DIR and PY exist only so the script can be tested elsewhere; leave them alone on the VPS.
set -euo pipefail

cd "${Z1_DIR:-/root/z1}"
PY="${PY:-./venv/bin/python}"
ZIP="${1:-z1_csv_files.zip}"
DB=z1_master.db
NEW=z1_new.db
KEEP=3   # backups to keep

[ -f "$ZIP" ] || { echo "Missing $ZIP"; exit 1; }
unzip -tq "$ZIP" >/dev/null || { echo "$ZIP is not a valid zip"; exit 1; }

q() { sqlite3 "$1" "$2"; }
cleanup_new() { rm -f "$NEW" "$NEW-wal" "$NEW-shm" "$NEW.fingerprint"; }

echo "== 1/6 build $NEW from $ZIP"
cleanup_new
"$PY" ingest.py --zip "$ZIP" --db "$NEW" || { cleanup_new; echo "Build failed; live database untouched."; exit 1; }
q "$NEW" "PRAGMA wal_checkpoint(TRUNCATE);" >/dev/null

echo "== 2/6 compare with the live database"
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

echo "== 3/6 archive the zip and record what changed"
mkdir -p archive
cp "$ZIP" "archive/z1-$(date +%Y%m%d-%H%M%S).zip"
if [ -f "$DB" ]; then
    rel=$(q "$NEW" "SELECT max(loaded_at) FROM release")
    has_rev=$(q "$DB" "SELECT count(*) FROM sqlite_master WHERE name='revision'")
    keep_old_rev=""
    [ "$has_rev" = 1 ] && keep_old_rev="INSERT INTO revision SELECT * FROM old.revision;"
    # revision rows: old_value NULL = newly published, new_value NULL = dropped, both set = revised
    q "$NEW" "ATTACH '$DB' AS old;
      $keep_old_rev
      INSERT OR IGNORE INTO release SELECT * FROM old.release;
      INSERT INTO revision SELECT '$rel', n.series_id, n.period, o.value, n.value
        FROM observation n JOIN old.observation o USING (series_id, period) WHERE o.value IS NOT n.value;
      INSERT INTO revision SELECT '$rel', n.series_id, n.period, NULL, n.value
        FROM observation n LEFT JOIN old.observation o USING (series_id, period) WHERE o.series_id IS NULL;
      INSERT INTO revision SELECT '$rel', o.series_id, o.period, o.value, NULL
        FROM old.observation o LEFT JOIN observation n USING (series_id, period) WHERE n.series_id IS NULL;"
    for what in "revised|old_value IS NOT NULL AND new_value IS NOT NULL" "newly published|old_value IS NULL" "dropped|new_value IS NULL"; do
        printf '%-22s %12s\n' "${what%%|*}" "$(q "$NEW" "SELECT count(*) FROM revision WHERE release='$rel' AND ${what#*|}")"
    done
else
    echo "no live database yet: nothing to compare"
fi

echo "== 4/6 back up the live database"
if [ -f "$DB" ]; then
    bak="$DB.bak-$(date +%Y%m%d-%H%M%S)"
    q "$DB" ".backup '$bak'"
    echo "saved $bak"
    ls -1t "$DB".bak-* 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
else
    echo "no live database yet, nothing to back up"
fi

echo "== 5/6 swap in the new database and restart"
systemctl stop z1-api
rm -f "$DB-wal" "$DB-shm"   # a stale WAL from the old file must never meet the new one
mv "$NEW" "$DB"
mv -f "$NEW.fingerprint" "$DB.fingerprint"   # keep the seal matched to the data
rm -f "$NEW-wal" "$NEW-shm"
systemctl start z1-api

echo "== 6/6 smoke test, fingerprint, shadow databases"
curl -fsS --retry 10 --retry-connrefused --retry-delay 1 http://127.0.0.1:8000/api/health
echo
"$PY" shadow.py verify
if [ "${REBUILD_SHADOWS:-1}" = 1 ]; then
    for spec in shadows/*.py; do
        [ -e "$spec" ] || continue
        name=$(basename "$spec" .py)
        # a failed shadow build never blocks the update: the Fed data is already live
        "$PY" shadow.py build "$name" || echo "WARNING: shadow '$name' failed to build; fix the spec and run: $PY shadow.py build $name"
    done
fi
echo "Done. Revision history for any series:  curl -H 'X-API-Key: ...' http://127.0.0.1:8000/api/series/<id>/revisions"
echo "To roll back, see the header of this script."
