# Z.1 Project

Fed Z.1 Financial Accounts in SQLite, served by a small FastAPI app.

## Files (all go in /root/z1/ on the VPS)

| File | Purpose |
|---|---|
| `schema.sql` | tables: series, series_table, observation, sector, release |
| `ingest.py` | loads `z1_csv_files.zip` (307 CSVs + data dictionaries) into SQLite |
| `app.py` | read-only JSON API |
| `z1-api.service` | systemd unit (binds 127.0.0.1:8000, not public) |
| `setup_vps.sh` | venv, load data, install service, smoke test |

## Install on the VPS

Upload the 5 files above plus `z1_csv_files.zip` to `/root/z1/` (SFTP, or `git clone` the repo there), then:

```
cd /root/z1
bash setup_vps.sh
```

The script installs `python3-venv`, `sqlite3` and `curl` if missing (apt), builds the venv, loads the zip, starts the `z1-api` service and runs a smoke test. If the Fed zip has another name: `ZIP=/root/z1/FRB_Z1_csv.zip bash setup_vps.sh`.

Re-running `setup_vps.sh` rebuilds the database from the zip.

The API is not public. To browse it from your own machine, tunnel it:
`ssh -L 8080:127.0.0.1:8000 root@<vps>` then open `http://127.0.0.1:8080/docs`.

## Quarterly refresh

Upload the new Fed zip, then `cd /root/z1 && bash update.sh /root/z1/<new_zip>`. It builds a scratch database, compares it with the live one, refuses to continue if the data shrank by more than 5% (override: `FORCE=1`), keeps the last 3 backups (`z1_master.db.bak-*`), swaps it in and restarts the service. Rollback: `systemctl stop z1-api; cp z1_master.db.bak-<timestamp> z1_master.db; systemctl start z1-api`.

## API

- `GET /api/health` (db status, total series and observations, latest release)
- `GET /api/series/{id}?start=2000:Q1&end=2026:Q2` (e.g. `FL152090005.Q`, household net worth)
- `GET /api/sector/{code}?prefix=FL` (all series in a 2-digit sector, e.g. `15` households; `prefix` optional)
- `GET /api/search?q=net worth&sector=15&prefix=FL`
- `GET /api/tables`, `GET /api/tables/{table_code}`

Values are in millions of dollars unless the series' `unit` says otherwise.

## Series codes

`FL152090005.Q` = `FL` (level) + `15` (sector) + `20900` (instrument) + `05` + `.Q`.
Prefixes in this release: FU, FA, FL, LM, FR, FV, FC, LA.

## Tested

On the Fed zip from this project: 307 files, 8,234 series, about 1.96M unique observations, 68 MB database, 13 s load.
Household net worth 2026:Q2 = 195,870,496 (millions).
Sector codes in `schema.sql` are limited to ones verified in the dictionary; the rest can be added from the series descriptions.
