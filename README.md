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

```
cd /root/z1          # put the 5 files above here, plus z1_csv_files.zip
bash setup_vps.sh
```

Re-running `setup_vps.sh` rebuilds the database from the zip (use it for each quarterly release).

## API

- `GET /api/health`
- `GET /api/series/{id}?start=2000:Q1&end=2026:Q2` (e.g. `FL152090005.Q`, household net worth)
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
