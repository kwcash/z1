"""Read-only JSON API over z1_master.db.

Run:  uvicorn app:app --host 127.0.0.1 --port 8000
"""
import hashlib
import os
import re
import secrets
import sqlite3
from contextlib import closing
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader

DB_PATH = Path(os.environ.get("Z1_DB", Path(__file__).parent / "z1_master.db"))
SERIES_RE = re.compile(r"^[A-Z]{2}[A-Z0-9_]{1,20}\.[QA]$")
SECTOR_RE = re.compile(r"^\d{2}$")
PERIOD_RE = re.compile(r"^\d{4}(:Q[1-4])?$")

# API keys: one "<name> <sha256 hex of key>" per line, managed by keys.sh.
# No keys file = open API (fine while it listens on 127.0.0.1 only).
# A keys file that holds no valid key refuses to start, so a bad edit can't silently open the API.
KEYS_FILE = Path(os.environ.get("Z1_KEYS_FILE", Path(__file__).parent / "api_keys.txt"))
key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def load_key_hashes() -> list[str]:
    if not KEYS_FILE.exists():
        return []
    hashes = []
    for line in KEYS_FILE.read_text().splitlines():
        parts = line.split()
        if len(parts) == 2 and re.fullmatch(r"[0-9a-f]{64}", parts[1]):
            hashes.append(parts[1])
    if not hashes:
        raise RuntimeError(f"{KEYS_FILE} exists but contains no valid keys; fix it or remove it")
    return hashes


KEY_HASHES = load_key_hashes()


def require_key(key: str | None = Security(key_header)):
    if not KEY_HASHES:
        return
    if key:
        digest = hashlib.sha256(key.encode()).hexdigest()
        ok = False
        for h in KEY_HASHES:  # no early exit: same work for every attempt
            ok |= secrets.compare_digest(digest, h)
        if ok:
            return
    raise HTTPException(401, "missing or invalid API key", headers={"WWW-Authenticate": "ApiKey"})


protected = [Depends(require_key)]

app = FastAPI(title="Z.1 Financial Accounts API", version="0.1.0")


def db() -> sqlite3.Connection:
    # read-only connection; one per request
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/api/health")
def health():
    try:
        with closing(db()) as c:
            # count the table itself: release.n_obs counts insert attempts, including replaced duplicates
            n_obs = c.execute("SELECT count(*) FROM observation").fetchone()[0]
            n_series = c.execute("SELECT count(*) FROM series").fetchone()[0]
            rel = c.execute("SELECT * FROM release ORDER BY loaded_at DESC LIMIT 1").fetchone()
    except sqlite3.Error as e:
        return JSONResponse(status_code=503, content={"status": "error", "db": DB_PATH.name, "detail": str(e)})
    return {
        "status": "ok",
        "auth": bool(KEY_HASHES),
        "db": DB_PATH.name,
        "total_series": n_series,
        "total_observations": n_obs,
        "release": dict(rel) if rel else None,
    }


@app.get("/api/series/{series_id}", dependencies=protected)
def get_series(
    series_id: str,
    start: str | None = Query(None, description="first period, e.g. 2000:Q1"),
    end: str | None = Query(None, description="last period, e.g. 2026:Q2"),
):
    if not SERIES_RE.match(series_id):
        raise HTTPException(400, "malformed series id")
    with closing(db()) as c:
        meta = c.execute("SELECT * FROM series WHERE series_id=?", (series_id,)).fetchone()
        if not meta:
            raise HTTPException(404, "series not found")
        for label, v in (("start", start), ("end", end)):
            if v and not PERIOD_RE.match(v):
                raise HTTPException(400, f"{label} must look like 2000 or 2000:Q1")
        annual = series_id.endswith(".A")
        sql = "SELECT period, value FROM observation WHERE series_id=?"
        args: list = [series_id]
        if start:   # periods are strings: '2000' sorts before '2000:Q1', so compare on the series' own frequency
            sql += " AND period >= ?"
            args.append(start[:4] if annual else start)
        if end:
            sql += " AND period <= ?"
            args.append(end[:4] if annual else (end + ":Q4" if ":" not in end else end))
        sql += " ORDER BY period"
        obs = [dict(r) for r in c.execute(sql, args)]
    return {"series": dict(meta), "observations": obs}


@app.get("/api/sector/{sector_code}", dependencies=protected)
def get_sector(
    sector_code: str,
    prefix: str | None = Query(None, description="FL, FA, FR, FU... to narrow the list"),
):
    if not SECTOR_RE.match(sector_code):
        raise HTTPException(400, "sector code must be 2 digits, e.g. 15")
    sql = (
        "SELECT series_id, prefix, instrument, freq, description, unit "
        "FROM series WHERE sector = ?"
    )
    args: list = [sector_code]
    if prefix:
        sql += " AND prefix = ?"
        args.append(prefix.upper())
    sql += " ORDER BY series_id"
    with closing(db()) as c:
        # name is null for codes not yet verified against the Fed dictionary (see schema.sql)
        name = c.execute("SELECT name FROM sector WHERE code=?", (sector_code,)).fetchone()
        series = [dict(r) for r in c.execute(sql, args)]
    if not series:
        raise HTTPException(404, "no series under this sector")
    return {
        "sector": {"code": sector_code, "name": name["name"] if name else None},
        "count": len(series),
        "series": series,
    }


@app.get("/api/search", dependencies=protected)
def search(
    q: str = Query(..., min_length=2, description="words in the series description"),
    prefix: str | None = Query(None, description="FL, FA, FR, FU..."),
    sector: str | None = Query(None, description="2-digit sector code"),
    limit: int = Query(25, ge=1, le=200),
):
    sql = "SELECT series_id, description, unit FROM series WHERE 1=1"
    args: list = []
    for word in q.split():
        sql += " AND description LIKE ? ESCAPE '\\'"
        args.append("%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    if prefix:
        sql += " AND prefix = ?"
        args.append(prefix.upper())
    if sector:
        sql += " AND sector = ?"
        args.append(sector)
    sql += " ORDER BY series_id LIMIT ?"
    args.append(limit)
    with closing(db()) as c:
        return [dict(r) for r in c.execute(sql, args)]


@app.get("/api/tables", dependencies=protected)
def tables():
    with closing(db()) as c:
        rows = c.execute(
            "SELECT table_code, max(table_title) AS title, count(*) AS n_series "
            "FROM series_table GROUP BY table_code ORDER BY table_code"
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/tables/{table_code}", dependencies=protected)
def table_series(table_code: str):
    with closing(db()) as c:
        rows = c.execute(
            "SELECT st.line_no, s.series_id, s.description FROM series_table st "
            "JOIN series s USING(series_id) WHERE st.table_code=? ORDER BY st.line_no",
            (table_code,),
        ).fetchall()
    if not rows:
        raise HTTPException(404, "table not found")
    return [dict(r) for r in rows]
