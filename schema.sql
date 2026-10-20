PRAGMA journal_mode = WAL;

-- One row per Z.1 series (FL/FA/FR/FU... mnemonic).
CREATE TABLE IF NOT EXISTS series (
    series_id   TEXT PRIMARY KEY,   -- e.g. 'FL152090005.Q'
    prefix      TEXT,               -- FL level, FA flow, FR revaluation, FU unadjusted flow, ...
    sector      TEXT,               -- 2-digit sector code, e.g. '15'
    instrument  TEXT,               -- 5-digit instrument code, e.g. '20900'
    suffix      TEXT,               -- trailing 2 digits
    freq        TEXT,               -- Q or A
    description TEXT,               -- from the Fed data dictionary
    unit        TEXT
);

-- Which published tables (e.g. 'F4.1.s') each series appears in, and on which line.
CREATE TABLE IF NOT EXISTS series_table (
    series_id   TEXT NOT NULL,
    table_code  TEXT NOT NULL,      -- csv file stem, e.g. 'F4_1_s'
    table_title TEXT,
    line_no     INTEGER,
    PRIMARY KEY (series_id, table_code)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS observation (
    series_id TEXT NOT NULL,
    period    TEXT NOT NULL,        -- '1990:Q1' or '1990'
    value     REAL,
    PRIMARY KEY (series_id, period)
) WITHOUT ROWID;

-- Only sector codes verified against the Fed dictionary are seeded.
CREATE TABLE IF NOT EXISTS sector (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

-- Values that changed between releases (written by update.sh); the old value is kept here.
CREATE TABLE IF NOT EXISTS revision (
    release   TEXT NOT NULL,        -- release.loaded_at of the release that changed it
    series_id TEXT NOT NULL,
    period    TEXT NOT NULL,
    old_value REAL,
    new_value REAL
);
CREATE INDEX IF NOT EXISTS idx_revision_series ON revision(series_id, period);

CREATE TABLE IF NOT EXISTS release (
    loaded_at TEXT PRIMARY KEY,
    source    TEXT,
    n_series  INTEGER,
    n_obs     INTEGER,
    n_files   INTEGER
);

CREATE INDEX IF NOT EXISTS idx_series_sector ON series(sector, prefix);
CREATE INDEX IF NOT EXISTS idx_series_instr  ON series(instrument, prefix);
CREATE INDEX IF NOT EXISTS idx_series_table  ON series_table(table_code);

INSERT OR IGNORE INTO sector(code, name) VALUES
 ('10','Nonfinancial corporate business'),
 ('11','Nonfinancial noncorporate business'),
 ('15','Households and nonprofit organizations'),
 ('21','State and local governments'),
 ('26','Rest of the world'),
 ('31','Federal government'),
 ('71','Monetary authority (central bank)'),
 ('76','U.S.-chartered depository institutions'),
 ('89','All sectors');
