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

## API keys

With no `api_keys.txt` the API is open (fine while it only listens on `127.0.0.1`). Before exposing it, create a key:

```
bash keys.sh add <name>      # prints the key once; stored hashed in api_keys.txt
bash keys.sh list
bash keys.sh revoke <name>   # the last key cannot be revoked
```

Callers send `X-API-Key: <key>`. `/api/health` stays open; every other `/api` route returns 401 without a valid key. A keys file with no valid key makes the app refuse to start, so a bad edit can't open the API. Keys are never in git (`api_keys.txt` is ignored).

## Public HTTPS (optional)

Needs a domain with an A record pointing at the VPS, and at least one API key:

```
DOMAIN=api.example.com EMAIL=you@example.com bash setup_nginx.sh
```

Installs nginx + certbot, proxies to the private API, rate-limits (10 req/s per IP) and gets a Let's Encrypt certificate that renews automatically.

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

## Fed data vs. shadow databases

`z1_master.db` is the clean copy of the Fed data and nothing else. Only `ingest.py` / `update.sh` write it; it records a content fingerprint (`z1_master.db.fingerprint`) so any change is detectable (`python shadow.py verify`).

Anything derived (per-capita, per-energy, ratios, logs in base e / 60 / any base, experiments) lives in a separate **shadow database** `shadow_<name>.db`, built by a spec in `shadows/<name>.py`:

```
python shadow.py list
python shadow.py build financialization
sqlite3 shadow_financialization.db "select * from experiment_result"
```

A shadow opens the Fed DB read-only, refuses to build if the fingerprint doesn't match, and stores that fingerprint in its `provenance` table, so every result says exactly which Fed data it came from. Tables: `derived_series` (formula + inputs for every metric), `derived_obs`, `external_input` (denominators you supply with a stated source), `experiment`, `experiment_result`.

Transforms (`transforms.py`): `log_base(s, base)`, `ratio` (annual denominators match each quarter), `growth`, `rolling_sum`, `index_to`, `to_base(x, 60)` (positional digits, e.g. `5;21,41,0`), `ols_slope`.

Per-capita etc.: drop a `period,value` CSV in `external/` and load it in a spec with `ctx.external(name, file, source)`. No outside numbers are bundled, since population and energy series should come from a source you choose and cite.

## Data integrity and history

- **Ingest aborts on disagreement.** If two CSV files give different values for the same series and period, `ingest.py` stops, lists the cells and keeps nothing. `release.n_obs` is the number of rows actually stored.
- **Revisions are kept.** `update.sh` copies each new zip to `archive/` (permanent) and records every changed value in the `revision` table (`release, series_id, period, old_value, new_value`). Rolling `.bak-*` copies are still made.
- **Rebuilds never happen in place.** `setup_vps.sh` and `update.sh` build `z1_new.db`, integrity-check it, then swap it in.
- **Sector codes are the Fed's 2-digit codes** (`15`). The three-digit codes in the Guide (`153`, `154`) are sector + the instrument's first digit (asset/liability side), not sectors.

## API reference (all under `/api`, all but `health` need `X-API-Key`)

| Route | What it does |
|---|---|
| `GET /series/{id}?start&end&asof&format` | observations. `asof=2026-07-15` gives the values as published at that release; `format=csv` downloads CSV |
| `GET /series/{id}/transform?kind=...` | `ln`, `log` (`log_base=60`), `yoy` (% vs a year ago), `pct` (`lag=n`), `logdiff`, `index` (`index_base=2000:Q1` = 100). The full history is transformed first, then clipped to `start`/`end` |
| `GET /compare?ids=A,B,C&kind=...` | up to 10 series (same frequency) aligned by period; accepts the same `kind`/`start`/`end`/`asof`/`format` |
| `GET /series/{id}/revisions` | every release in which a value changed (`old_value` null = newly published, `new_value` null = dropped) |
| `GET /releases` | releases held in this database (use a date as `asof`) |
| `GET /sector/{code}`, `/search`, `/tables`, `/tables/{code}` | browsing (search escapes `%` and `_`) |

`asof` and `revisions` return 409 until the first `update.sh` run creates history.

## Quarterly update (when the Fed publishes a new Z.1)

```
scp new_z1.zip root@<vps>:/root/z1/        # from the Fed's "Z.1 CSV files" download
ssh root@<vps>
cd /root/z1 && bash update.sh /root/z1/new_z1.zip
```

`update.sh` explains itself at the top of the file: it builds and checks a new database first, stops if anything looks wrong, archives the zip, records revisions, swaps the new database in, restarts the API and rebuilds the shadow databases. Rollback instructions are in its header.

## Guide corrections

`GUIDE_FIX.md` lists every sector/instrument-code edit needed in `Z1_Guide_EDITED.docx`; `python guide_appendix.py` regenerates the corrected Appendix B and C tables from the database.
