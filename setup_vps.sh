#!/usr/bin/env bash
# Run on the VPS from /root/z1 after copying these files there:
#   cd /root/z1 && bash setup_vps.sh
# Expects the Fed zip at /root/z1/z1_csv_files.zip (override: ZIP=path bash setup_vps.sh)
set -euo pipefail

cd /root/z1
ZIP="${ZIP:-/root/z1/z1_csv_files.zip}"
[ -f "$ZIP" ] || { echo "Missing $ZIP"; exit 1; }

echo "== 1/4 virtual environment"
[ -d venv ] || python3 -m venv venv
./venv/bin/pip install --quiet --upgrade pip
./venv/bin/pip install --quiet fastapi "uvicorn[standard]"

echo "== 2/4 load data (rebuilds z1_master.db)"
rm -f z1_master.db z1_master.db-wal z1_master.db-shm
./venv/bin/python ingest.py --zip "$ZIP" --db z1_master.db

echo "== 3/4 install and start the service"
cp z1-api.service /etc/systemd/system/z1-api.service
systemctl daemon-reload
systemctl enable --now z1-api
sleep 2
systemctl --no-pager --lines=5 status z1-api || true

echo "== 4/4 smoke test"
curl -fsS http://127.0.0.1:8000/api/health
echo
curl -fsS "http://127.0.0.1:8000/api/series/FL152090005.Q?start=2025:Q1" | head -c 600
echo
echo "Done. API listens on 127.0.0.1:8000 only (not public)."
