#!/usr/bin/env bash
# Run on the VPS from /root/z1 after copying these files there:
#   cd /root/z1 && bash setup_vps.sh
# Expects the Fed zip at /root/z1/z1_csv_files.zip (override: ZIP=path bash setup_vps.sh)
set -euo pipefail

cd /root/z1
ZIP="${ZIP:-/root/z1/z1_csv_files.zip}"
[ -f "$ZIP" ] || { echo "Missing $ZIP"; exit 1; }

echo "== 1/5 system packages (python3-venv, sqlite3, curl)"
if command -v apt-get >/dev/null; then
    need=()
    python3 -c "import venv, ensurepip" 2>/dev/null || need+=(python3-venv)
    command -v sqlite3 >/dev/null || need+=(sqlite3)
    command -v curl >/dev/null || need+=(curl)
    if [ "${#need[@]}" -gt 0 ]; then
        echo "installing: ${need[*]}"
        apt-get update -qq
        apt-get install -y -qq "${need[@]}"
    fi
fi

echo "== 2/5 virtual environment"
[ -x venv/bin/pip ] || python3 -m venv --clear venv
./venv/bin/pip install --quiet --upgrade pip
./venv/bin/pip install --quiet fastapi "uvicorn[standard]"

echo "== 3/5 load data (builds z1_new.db, then swaps it in)"
rm -f z1_new.db z1_new.db-wal z1_new.db-shm
./venv/bin/python ingest.py --zip "$ZIP" --db z1_new.db
sqlite3 z1_new.db "PRAGMA wal_checkpoint(TRUNCATE);" >/dev/null
[ "$(sqlite3 z1_new.db "PRAGMA integrity_check;")" = "ok" ] || { echo "integrity check failed; live database untouched"; exit 1; }
systemctl stop z1-api 2>/dev/null || true
rm -f z1_master.db-wal z1_master.db-shm
mv z1_new.db z1_master.db
mv -f z1_new.db.fingerprint z1_master.db.fingerprint

echo "== 4/5 install and start the service"
cp z1-api.service /etc/systemd/system/z1-api.service
systemctl daemon-reload
systemctl enable z1-api
systemctl restart z1-api
systemctl --no-pager --lines=5 status z1-api || true

echo "== 5/5 smoke test"
curl -fsS --retry 10 --retry-connrefused --retry-delay 1 http://127.0.0.1:8000/api/health
echo
if [ -f api_keys.txt ]; then
    echo "API keys are enabled (keys.sh); skipping the authenticated checks."
else
    curl -fsS "http://127.0.0.1:8000/api/series/FL152090005.Q?start=2025:Q1" | head -c 600
    echo
    curl -fsS "http://127.0.0.1:8000/api/sector/15?prefix=FL" | head -c 300
    echo
fi
echo "Done. API listens on 127.0.0.1:8000 only (not public)."
echo "From your own machine:  ssh -L 8080:127.0.0.1:8000 root@<vps>   then open http://127.0.0.1:8080/docs"
