-- Two caches the crawler needs, both of which exist to avoid spending quota
-- on something already known.

-- Repository language and star count. Search results carry neither, so every
-- distinct repository costs a request unless it is remembered. Neither field
-- moves fast enough to matter for scoring, so this is refreshed weekly.
CREATE TABLE IF NOT EXISTS repo_meta (
    name       TEXT PRIMARY KEY,
    language   TEXT,
    stars      INTEGER,
    archived   INTEGER NOT NULL DEFAULT 0,
    is_fork    INTEGER NOT NULL DEFAULT 0,
    fetched_at INTEGER NOT NULL
);

-- Entity tags from previous runs. A conditional request that comes back 304
-- costs no rate limit at all, which is what makes polling a watchlist every
-- night affordable, but only if the tags outlive the process.
CREATE TABLE IF NOT EXISTS http_etag (
    url        TEXT PRIMARY KEY,
    etag       TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);
