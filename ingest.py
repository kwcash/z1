#!/usr/bin/env python3
"""Load the Fed's Z.1 CSV zip (z1_csv_files.zip) into SQLite.

The zip contains:
  csv/<table>.csv               one header row ('date', series ids...), then one row per period
  data_dictionary/<table>.txt   tab-separated: series_id, description, line, table title, units

Usage:
    python ingest.py --zip z1_csv_files.zip --db z1_master.db
"""
import argparse
import csv
import io
import re
import sqlite3
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import z1lib

MNEMONIC = re.compile(r"^(?P<prefix>[A-Z]{2})(?P<sector>\d{2})(?P<instrument>\d{5})(?P<suffix>\d{2})\.(?P<freq>[QA])$")
MISSING = {"", "ND", "NA", "NC", "NM"}
LINE = re.compile(r"(\d+)")


def parse_mnemonic(series_id: str) -> dict:
    """FL152090005.Q -> prefix FL, sector 15, instrument 20900, suffix 05, freq Q."""
    m = MNEMONIC.match(series_id)
    if m:
        return m.groupdict()
    base, _, freq = series_id.partition(".")
    return {"prefix": base[:2], "sector": None, "instrument": None, "suffix": None, "freq": freq or None}


def to_float(s: str):
    s = s.strip()
    if s in MISSING:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def read_dictionary(zf: zipfile.ZipFile, stem: str):
    """Yield (series_id, description, line_no, table_title, unit) for one table."""
    name = f"data_dictionary/{stem}.txt"
    try:
        raw = zf.read(name).decode("utf-8-sig", "replace")
    except KeyError:
        return
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 2 or not parts[0].strip():
            continue
        sid = parts[0].strip()
        desc = parts[1].strip()
        m = LINE.search(parts[2]) if len(parts) > 2 else None
        title = parts[3].strip() if len(parts) > 3 else None
        unit = parts[4].strip() if len(parts) > 4 else None
        yield sid, desc, int(m.group(1)) if m else None, title, unit


def load(zf: zipfile.ZipFile, conn: sqlite3.Connection, source: str) -> tuple[int, int, int]:
    csv_names = sorted(n for n in zf.namelist() if n.startswith("csv/") and n.lower().endswith(".csv"))
    seen_series: set[str] = set()
    values: dict[tuple[str, str], float] = {}   # every (series, period) seen, to catch files that disagree
    conflicts: list[str] = []

    with conn:
        for name in csv_names:
            stem = Path(name).stem

            # 1) dictionary: series metadata + table membership
            for sid, desc, line_no, title, unit in read_dictionary(zf, stem):
                p = parse_mnemonic(sid)
                conn.execute(
                    "INSERT OR IGNORE INTO series(series_id,prefix,sector,instrument,suffix,freq,description,unit) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (sid, p["prefix"], p["sector"], p["instrument"], p["suffix"], p["freq"], desc, unit),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO series_table VALUES (?,?,?,?)", (sid, stem, title, line_no)
                )

            # 2) observations
            reader = csv.reader(io.TextIOWrapper(zf.open(name), encoding="utf-8-sig", newline=""))
            header = next(reader, None)
            if not header:
                continue
            ids = [h.strip() for h in header[1:]]
            for sid in ids:
                if sid not in seen_series:
                    seen_series.add(sid)
                    p = parse_mnemonic(sid)
                    # series with no dictionary entry still get a row
                    conn.execute(
                        "INSERT OR IGNORE INTO series(series_id,prefix,sector,instrument,suffix,freq) VALUES (?,?,?,?,?,?)",
                        (sid, p["prefix"], p["sector"], p["instrument"], p["suffix"], p["freq"]),
                    )
            batch = []
            for row in reader:
                if not row or not row[0].strip():
                    continue
                period = row[0].strip()
                for sid, cell in zip(ids, row[1:]):
                    v = to_float(cell)
                    if v is None:
                        continue
                    old = values.get((sid, period))
                    if old is None:
                        values[(sid, period)] = v
                        batch.append((sid, period, v))
                    elif old != v:
                        conflicts.append(f"{sid} {period}: {old} vs {v} (in {stem})")
            conn.executemany("INSERT INTO observation VALUES (?,?,?)", batch)

        if conflicts:
            # raising inside `with conn` rolls everything back: nothing half-loaded is kept
            raise SystemExit(f"ABORT: {len(conflicts)} cells disagree between CSV files, e.g.:\n  " + "\n  ".join(conflicts[:20]))
        n_obs = len(values)

        n_series = conn.execute("SELECT count(*) FROM series").fetchone()[0]
        conn.execute(
            "INSERT OR REPLACE INTO release VALUES (?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"), source, n_series, n_obs, len(csv_names)),
        )
    return n_series, n_obs, len(csv_names)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zip", type=Path, required=True)
    ap.add_argument("--db", type=Path, default=Path("z1_master.db"))
    a = ap.parse_args()

    conn = sqlite3.connect(a.db)
    conn.executescript((Path(__file__).parent / "schema.sql").read_text())
    with zipfile.ZipFile(a.zip) as zf:
        n_series, n_obs, n_files = load(zf, conn, a.zip.name)
    n_db_obs = conn.execute("SELECT count(*) FROM observation").fetchone()[0]
    z1lib.fingerprint_file(a.db).write_text(z1lib.fingerprint(conn) + "\n")
    print(f"Read {n_files} CSV files: {n_series} unique series, {n_db_obs} unique observations in {a.db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
