-- State that belonged to the original CLI: which issues it had already shown
-- you, and a week-long cache of repository metadata. Migration 004 drops both,
-- now that the CLI reads the corpus instead. This file stays because
-- migrations are a record of what happened, not a description of the schema.

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
