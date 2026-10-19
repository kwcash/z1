"""Read-only JSON API over z1_master.db.

Run:  uvicorn app:app --host 127.0.0.1 --port 8000
"""
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query

DB_PATH = Path(os.environ.get("Z1_DB", Path(__file__).parent / "z1_master.db"))
SERIES_RE = re.compile(r"^[A-Z]{2}[A-Z0-9_]{1,20}\.[QA]$")

app = FastAPI(title="Z.1 Financial Accounts API", version="0.1.0")


def db() -> sqlite3.Connection:
    # read-only connection; one per request
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/api/health")
def health():
    with closing(db()) as c:
        rel = c.execute("SELECT * FROM release ORDER BY loaded_at DESC LIMIT 1").fetchone()
    return {"status": "ok", "release": dict(rel) if rel else None}


@app.get("/api/series/{series_id}")
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
        sql = "SELECT period, value FROM observation WHERE series_id=?"
        args: list = [series_id]
        if start:
            sql += " AND period >= ?"
            args.append(start)
        if end:
            sql += " AND period <= ?"
            args.append(end)
        sql += " ORDER BY period"
        obs = [dict(r) for r in c.execute(sql, args)]
    return {"series": dict(meta), "observations": obs}


@app.get("/api/search")
def search(
    q: str = Query(..., min_length=2, description="words in the series description"),
    prefix: str | None = Query(None, description="FL, FA, FR, FU..."),
    sector: str | None = Query(None, description="2-digit sector code"),
    limit: int = Query(25, ge=1, le=200),
):
    sql = "SELECT series_id, description, unit FROM series WHERE 1=1"
    args: list = []
    for word in q.split():
        sql += " AND description LIKE ?"
        args.append(f"%{word}%")
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


@app.get("/api/tables")
def tables():
    with closing(db()) as c:
        rows = c.execute(
            "SELECT table_code, max(table_title) AS title, count(*) AS n_series "
            "FROM series_table GROUP BY table_code ORDER BY table_code"
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/tables/{table_code}")
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
