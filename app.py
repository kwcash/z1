"""Read-only JSON API over z1_master.db.

Run:  uvicorn app:app --host 127.0.0.1 --port 8000
"""
import csv
import hashlib
import io
import os
import re
import secrets
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Security
from fastapi.responses import JSONResponse, Response
from fastapi.security import APIKeyHeader

import transforms as tf

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

app = FastAPI(title="Z.1 Financial Accounts API", version="0.2.0")


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


ASOF_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}(\+00:00|Z)?)?$")
Kind = Literal["level", "ln", "log", "yoy", "pct", "logdiff", "index"]
Fmt = Literal["json", "csv"]


def check_series_id(series_id: str):
    if not SERIES_RE.match(series_id):
        raise HTTPException(400, "malformed series id")


def get_meta(c: sqlite3.Connection, series_id: str) -> dict:
    check_series_id(series_id)
    meta = c.execute("SELECT * FROM series WHERE series_id=?", (series_id,)).fetchone()
    if not meta:
        raise HTTPException(404, "series not found")
    return dict(meta)


def has_revisions(c: sqlite3.Connection) -> bool:
    return c.execute("SELECT 1 FROM sqlite_master WHERE name='revision'").fetchone() is not None


def check_window(start: str | None, end: str | None):
    for label, v in (("start", start), ("end", end)):
        if v and not PERIOD_RE.match(v):
            raise HTTPException(400, f"{label} must look like 2000 or 2000:Q1")


def clip(s: dict, series_id: str, start: str | None, end: str | None) -> dict:
    """Keep start..end. Periods are strings ('2000' sorts before '2000:Q1'), so compare on the series' own frequency."""
    annual = series_id.endswith(".A")
    lo = (start[:4] if annual else start) if start else None
    hi = (end[:4] if annual else (end if ":" in end else end + ":Q4")) if end else None
    return {p: v for p, v in s.items() if (lo is None or p >= lo) and (hi is None or p <= hi)}


def fetch(c: sqlite3.Connection, series_id: str, asof: str | None = None) -> dict[str, float]:
    """The whole series {period: value}, optionally as the Fed published it at `asof` (a release date/time)."""
    obs = dict(c.execute("SELECT period, value FROM observation WHERE series_id=? ORDER BY period", (series_id,)).fetchall())
    if asof:
        if not ASOF_RE.match(asof):
            raise HTTPException(400, "asof must look like 2026-07-15 or 2026-07-15T12:00:00+00:00")
        if not has_revisions(c):
            raise HTTPException(409, "no revision history in this database yet (it starts with the next update.sh run)")
        ts = asof if "T" in asof else asof + "T23:59:59+00:00"
        seen = set()
        # the earliest later revision of a period holds what was published at `asof`; old_value NULL = not yet published
        for period, old in c.execute(
            "SELECT period, old_value FROM revision WHERE series_id=? AND release > ? ORDER BY release, rowid", (series_id, ts)
        ):
            if period in seen:
                continue
            seen.add(period)
            if old is None:
                obs.pop(period, None)
            else:
                obs[period] = old
    return dict(sorted(obs.items()))


def apply_transform(s: dict, series_id: str, kind: str, log_base: float, index_base: str | None, lag: int | None) -> dict:
    annual = series_id.endswith(".A")
    if kind == "level":
        return s
    if kind == "ln":
        return tf.log_base(s)
    if kind == "log":
        if log_base <= 0 or log_base == 1:
            raise HTTPException(400, "log_base must be positive and not 1")
        return tf.log_base(s, log_base)
    if kind == "yoy":
        return tf.pct_change(s, 1 if annual else 4)
    if kind == "pct":
        return tf.pct_change(s, lag or 1)
    if kind == "logdiff":
        return tf.growth(s, lag or (1 if annual else 4))
    if kind == "index":
        if not index_base or index_base not in s:
            raise HTTPException(400, "index_base must be a period present in the data, e.g. 2000:Q1")
        return tf.index_to(s, index_base)
    raise HTTPException(400, "unknown kind")


def csv_response(header: list, rows, filename: str) -> Response:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/api/series/{series_id}", dependencies=protected)
def get_series(
    series_id: str,
    start: str | None = Query(None, description="first period, e.g. 2000:Q1"),
    end: str | None = Query(None, description="last period, e.g. 2026:Q2"),
    asof: str | None = Query(None, description="values as published at this release date, e.g. 2026-07-15"),
    format: Fmt = Query("json"),
):
    check_window(start, end)
    with closing(db()) as c:
        meta = get_meta(c, series_id)
        s = clip(fetch(c, series_id, asof), series_id, start, end)
    if format == "csv":
        return csv_response(["period", "value"], s.items(), f"{series_id}.csv")
    return {"series": meta, "asof": asof, "observations": [{"period": p, "value": v} for p, v in s.items()]}


@app.get("/api/series/{series_id}/transform", dependencies=protected)
def get_transform(
    series_id: str,
    kind: Kind = Query("level", description="ln | log (set log_base, e.g. 60) | yoy (% vs a year ago) | pct (% over `lag`) | logdiff | index (set index_base)"),
    log_base: float = Query(10.0, description="base for kind=log"),
    index_base: str | None = Query(None, description="period that equals 100 for kind=index"),
    lag: int | None = Query(None, ge=1, le=40, description="periods for pct/logdiff; default 1 (pct) or a year (logdiff)"),
    start: str | None = None,
    end: str | None = None,
    asof: str | None = None,
    format: Fmt = Query("json"),
):
    check_window(start, end)
    with closing(db()) as c:
        meta = get_meta(c, series_id)
        s = fetch(c, series_id, asof)
    # transform the full history first, so yoy/index have their earlier periods; then clip to the window
    out = clip(apply_transform(s, series_id, kind, log_base, index_base, lag), series_id, start, end)
    if format == "csv":
        return csv_response(["period", "value"], out.items(), f"{series_id}-{kind}.csv")
    return {"series": meta, "kind": kind, "observations": [{"period": p, "value": v} for p, v in out.items()]}


@app.get("/api/compare", dependencies=protected)
def compare(
    ids: str = Query(..., description="comma-separated series ids, same frequency, at most 10"),
    kind: Kind = Query("level"),
    log_base: float = Query(10.0),
    index_base: str | None = Query(None),
    lag: int | None = Query(None, ge=1, le=40),
    start: str | None = None,
    end: str | None = None,
    asof: str | None = None,
    format: Fmt = Query("json"),
):
    id_list = list(dict.fromkeys(i.strip() for i in ids.split(",") if i.strip()))
    if not 1 <= len(id_list) <= 10:
        raise HTTPException(400, "give 1 to 10 series ids")
    for i in id_list:
        check_series_id(i)
    if len({i.rsplit(".", 1)[1] for i in id_list}) > 1:
        raise HTTPException(400, "series must all be quarterly (.Q) or all annual (.A)")
    check_window(start, end)
    cols, metas = {}, []
    with closing(db()) as c:
        for i in id_list:
            m = get_meta(c, i)
            metas.append({k: m[k] for k in ("series_id", "description", "unit")})
            cols[i] = clip(apply_transform(fetch(c, i, asof), i, kind, log_base, index_base, lag), i, start, end)
    periods = sorted(set().union(*cols.values()))
    if format == "csv":
        return csv_response(["period", *id_list], ([p, *[cols[i].get(p) for i in id_list]] for p in periods), "compare.csv")
    return {
        "kind": kind,
        "periods": periods,
        "series": [{**m, "values": [cols[m["series_id"]].get(p) for p in periods]} for m in metas],
    }


@app.get("/api/series/{series_id}/revisions", dependencies=protected)
def series_revisions(
    series_id: str,
    start: str | None = None,
    end: str | None = None,
    limit: int = Query(500, ge=1, le=5000),
    format: Fmt = Query("json"),
):
    """What changed for this series in each release. old_value null = period newly published; new_value null = dropped."""
    check_window(start, end)
    with closing(db()) as c:
        get_meta(c, series_id)
        if not has_revisions(c):
            raise HTTPException(409, "no revision history in this database yet (it starts with the next update.sh run)")
        sql, args = "SELECT release, period, old_value, new_value FROM revision WHERE series_id=?", [series_id]
        if start:
            sql += " AND period >= ?"; args.append(start)
        if end:
            sql += " AND period <= ?"; args.append(end if ":" in end or not series_id.endswith(".Q") else end + ":Q4")
        sql += " ORDER BY release DESC, period LIMIT ?"
        args.append(limit)
        rows = [dict(r) for r in c.execute(sql, args)]
    if format == "csv":
        return csv_response(["release", "period", "old_value", "new_value"], [list(r.values()) for r in rows], f"{series_id}-revisions.csv")
    return {"series_id": series_id, "count": len(rows), "revisions": rows}


@app.get("/api/releases", dependencies=protected)
def releases():
    """Releases held in this database (use a loaded_at date as `asof`)."""
    with closing(db()) as c:
        return [dict(r) for r in c.execute("SELECT * FROM release ORDER BY loaded_at DESC")]


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
