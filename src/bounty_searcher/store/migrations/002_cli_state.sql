-- State belonging to the original CLI: which issues it has already shown you,
-- and a week-long cache of repo metadata. Both are superseded by the corpus
-- above (first_seen_at, and the repository columns on bounty) and go when the
-- CLI moves onto it. Declared here so there is one schema and one runner.

CREATE TABLE IF NOT EXISTS seen (
    key        TEXT PRIMARY KEY,
    repo       TEXT NOT NULL,
    number     INTEGER NOT NULL,
    title      TEXT,
    url        TEXT,
    amount     REAL,
    score      REAL,
    first_seen REAL NOT NULL,
    last_seen  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS repo_cache (
    name       TEXT PRIMARY KEY,
    data       TEXT NOT NULL,
    fetched_at REAL NOT NULL
);
