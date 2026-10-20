#!/usr/bin/env python3
"""Build shadow databases: derived metrics and experiments layered on the sealed Fed database.

    python shadow.py build financialization        # runs shadows/financialization.py -> shadow_financialization.db
    python shadow.py list
    python shadow.py seal                          # (re)write the Fed DB fingerprint; ingest.py does this automatically
    python shadow.py verify                        # Fed DB still matches its fingerprint?

A shadow never touches the Fed DB: it is opened read-only and the shadow DB records its fingerprint.
A spec is shadows/<name>.py defining run(ctx).
"""
import argparse
import csv
import importlib.util
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import transforms
import z1lib

HERE = Path(__file__).parent
SCHEMA = """
CREATE TABLE derived_series (
    series_id TEXT PRIMARY KEY, label TEXT, formula TEXT, unit TEXT, inputs TEXT);   -- inputs: comma-separated Fed ids / external names
CREATE TABLE derived_obs (
    series_id TEXT NOT NULL, period TEXT NOT NULL, value REAL, text TEXT,
    PRIMARY KEY (series_id, period)) WITHOUT ROWID;
CREATE TABLE external_input (                                                         -- user-supplied denominators (population, energy...)
    name TEXT NOT NULL, period TEXT NOT NULL, value REAL, source TEXT,
    PRIMARY KEY (name, period)) WITHOUT ROWID;
CREATE TABLE experiment (id TEXT PRIMARY KEY, hypothesis TEXT, method TEXT, created_at TEXT);
CREATE TABLE experiment_result (experiment_id TEXT, metric TEXT, value REAL, note TEXT);
CREATE TABLE provenance (key TEXT PRIMARY KEY, value TEXT);
"""


class Ctx:
    def __init__(self, master: sqlite3.Connection, db: sqlite3.Connection):
        self.master, self.db, self.t = master, db, transforms

    def fed(self, series_id: str) -> dict:
        s = z1lib.load_series(self.master, series_id)
        if not s:
            raise KeyError(f"{series_id} not in the Fed database")
        return s

    def external(self, name: str, csv_path: str, source: str) -> dict:
        """Import external/<csv_path> (columns: period,value) as an input; the source must be stated."""
        with open(HERE / "external" / csv_path, newline="") as f:
            rows = {r["period"]: float(r["value"]) for r in csv.DictReader(f)}
        self.db.executemany("INSERT OR REPLACE INTO external_input VALUES (?,?,?,?)", [(name, p, v, source) for p, v in rows.items()])
        return rows

    def put(self, series_id: str, values: dict, label: str, formula: str, unit: str, inputs: list[str], text: dict | None = None):
        self.db.execute("INSERT OR REPLACE INTO derived_series VALUES (?,?,?,?,?)", (series_id, label, formula, unit, ",".join(inputs)))
        self.db.executemany("INSERT OR REPLACE INTO derived_obs VALUES (?,?,?,?)",
                            [(series_id, p, v, (text or {}).get(p)) for p, v in values.items()])
        return values

    def experiment(self, exp_id: str, hypothesis: str, method: str):
        self.db.execute("INSERT OR REPLACE INTO experiment VALUES (?,?,?,?)", (exp_id, hypothesis, method, datetime.now(timezone.utc).isoformat(timespec="seconds")))

    def result(self, exp_id: str, metric: str, value, note: str = ""):
        self.db.execute("INSERT INTO experiment_result VALUES (?,?,?,?)", (exp_id, metric, value, note))


def master_checked() -> sqlite3.Connection:
    if not z1lib.MASTER.exists():
        sys.exit(f"{z1lib.MASTER} missing: run setup_vps.sh / ingest.py first")
    conn = z1lib.open_master()
    fp_file = z1lib.fingerprint_file(z1lib.MASTER)
    if fp_file.exists() and fp_file.read_text().strip() != z1lib.fingerprint(conn):
        sys.exit("Fed database does not match its fingerprint; refusing to build on it (python shadow.py verify)")
    return conn


def build(name: str) -> Path:
    spec_path = HERE / "shadows" / f"{name}.py"
    if not spec_path.exists():
        sys.exit(f"no spec {spec_path}")
    spec = importlib.util.spec_from_file_location(f"shadow_{name}", spec_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    master = master_checked()
    out = HERE / f"shadow_{name}.db"
    tmp = out.with_suffix(".db.tmp")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript(SCHEMA)
    ctx = Ctx(master, db)
    mod.run(ctx)
    db.executemany("INSERT INTO provenance VALUES (?,?)", [
        ("spec", name), ("built_at", datetime.now(timezone.utc).isoformat(timespec="seconds")),
        ("fed_fingerprint", z1lib.fingerprint(master)),
        ("fed_release", str(master.execute("SELECT loaded_at FROM release ORDER BY loaded_at DESC LIMIT 1").fetchone()))])
    db.commit()
    db.close()
    tmp.replace(out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list"); sub.add_parser("seal"); sub.add_parser("verify")
    sub.add_parser("build").add_argument("name")
    a = ap.parse_args()
    if a.cmd == "list":
        for p in sorted((HERE / "shadows").glob("*.py")):
            print(p.stem, "(built)" if (HERE / f"shadow_{p.stem}.db").exists() else "")
    elif a.cmd == "seal":
        z1lib.fingerprint_file(z1lib.MASTER).write_text(z1lib.fingerprint(z1lib.open_master()) + "\n")
        print("sealed")
    elif a.cmd == "verify":
        ok = z1lib.fingerprint_file(z1lib.MASTER).read_text().strip() == z1lib.fingerprint(z1lib.open_master())
        print("OK: Fed database unchanged" if ok else "MISMATCH: Fed database has changed")
        return 0 if ok else 1
    else:
        print("built", build(a.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
