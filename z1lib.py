"""Shared helpers: read-only access to the sealed Fed database and its content fingerprint."""
import hashlib
import sqlite3
from pathlib import Path

MASTER = Path(__file__).parent / "z1_master.db"


def open_master(path: Path = MASTER) -> sqlite3.Connection:
    """The Fed database is only ever opened read-only by anything except ingest.py."""
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def fingerprint(conn: sqlite3.Connection) -> str:
    """SHA-256 over every (series_id, period, value) in order: changes iff the Fed data changes."""
    h = hashlib.sha256()
    for sid, period, value in conn.execute("SELECT series_id, period, value FROM observation ORDER BY series_id, period"):
        h.update(f"{sid}|{period}|{value!r}\n".encode())
    return h.hexdigest()


def fingerprint_file(db: Path) -> Path:
    return db.with_name(db.name + ".fingerprint")


def load_series(conn: sqlite3.Connection, series_id: str) -> dict[str, float]:
    return dict(conn.execute("SELECT period, value FROM observation WHERE series_id=?", (series_id,)))
