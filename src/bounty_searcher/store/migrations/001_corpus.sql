-- The corpus: bounties, their scores, your triage decisions, and the scans
-- that found them. Every timestamp column is whole seconds since the epoch,
-- and every money column is minor units.

CREATE TABLE IF NOT EXISTS bounty (
    id                INTEGER PRIMARY KEY,
    repo              TEXT    NOT NULL,
    number            INTEGER NOT NULL,
    source            TEXT    NOT NULL,
    title             TEXT    NOT NULL,
    url               TEXT    NOT NULL,
    state             TEXT    NOT NULL,
    body              TEXT    NOT NULL DEFAULT '',
    labels            TEXT    NOT NULL DEFAULT '[]',  -- JSON array
    comments          INTEGER NOT NULL DEFAULT 0,
    assignee          TEXT,
    language          TEXT,
    stars             INTEGER,
    is_fork           INTEGER NOT NULL DEFAULT 0,
    claim_reason      TEXT,
    amount_minor      INTEGER,
    amount_currency   TEXT,
    amount_confidence TEXT,
    amount_field      TEXT,
    amount_pattern    TEXT,
    amount_start      INTEGER,
    amount_end        INTEGER,
    amount_text       TEXT,
    created_at        INTEGER NOT NULL,
    updated_at        INTEGER NOT NULL,
    first_seen_at     INTEGER NOT NULL,
    last_seen_at      INTEGER NOT NULL,
    -- When a re-scan last found something materially different, and the hash
    -- that decides it. Together they drive the "changed" view.
    changed_at        INTEGER NOT NULL,
    content_hash      TEXT    NOT NULL,
    UNIQUE (repo, number)
);

-- Everything the interface orders by lives here, denormalised, so ordering is
-- a single index scan rather than a join and a sort.
CREATE TABLE IF NOT EXISTS bounty_score (
    bounty_id      INTEGER PRIMARY KEY REFERENCES bounty(id) ON DELETE CASCADE,
    total          REAL NOT NULL,
    payout         REAL NOT NULL,
    language       REAL NOT NULL,
    effort         REAL NOT NULL,
    freshness      REAL NOT NULL,
    competition    REAL NOT NULL,
    repository     REAL NOT NULL,
    suspect_reason TEXT,
    weights_hash   TEXT    NOT NULL,
    scored_at      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS triage (
    bounty_id    INTEGER PRIMARY KEY REFERENCES bounty(id) ON DELETE CASCADE,
    status       TEXT    NOT NULL,
    snooze_until INTEGER,
    updated_at   INTEGER NOT NULL
);

-- Every transition, so undo is a replay rather than a guess. `batch` groups a
-- run of dismissals made in one gesture under a single undo token.
CREATE TABLE IF NOT EXISTS triage_journal (
    id                INTEGER PRIMARY KEY,
    batch             TEXT    NOT NULL,
    bounty_id         INTEGER NOT NULL REFERENCES bounty(id) ON DELETE CASCADE,
    from_status       TEXT    NOT NULL,
    from_snooze_until INTEGER,
    to_status         TEXT    NOT NULL,
    to_snooze_until   INTEGER,
    created_at        INTEGER NOT NULL,
    undone_at         INTEGER
);

CREATE TABLE IF NOT EXISTS scan_run (
    id              INTEGER PRIMARY KEY,
    started_at      INTEGER NOT NULL,
    finished_at     INTEGER,
    status          TEXT    NOT NULL,
    planned_queries INTEGER NOT NULL DEFAULT 0,
    error           TEXT
);

-- One row per planned query. A completed row is never run again within a run,
-- which is what makes an interrupted sweep resumable, and `results` against
-- `new_bounties` shows which queries earn their quota.
CREATE TABLE IF NOT EXISTS scan_query (
    id           INTEGER PRIMARY KEY,
    run_id       INTEGER NOT NULL REFERENCES scan_run(id) ON DELETE CASCADE,
    source       TEXT    NOT NULL,
    query        TEXT    NOT NULL,
    status       TEXT    NOT NULL,
    started_at   INTEGER NOT NULL,
    finished_at  INTEGER,
    results      INTEGER NOT NULL DEFAULT 0,
    new_bounties INTEGER NOT NULL DEFAULT 0,
    error        TEXT,
    UNIQUE (run_id, source, query)
);

-- Indices, one per actual read pattern.
-- Keyset pagination down the ranked list, with the identity tie break.
CREATE INDEX IF NOT EXISTS bounty_score_ranked
    ON bounty_score(total DESC, bounty_id DESC);
-- The "new since last scan" view.
CREATE INDEX IF NOT EXISTS bounty_first_seen
    ON bounty(first_seen_at DESC, id DESC);
-- Payout ordering, and the minimum-amount filter.
CREATE INDEX IF NOT EXISTS bounty_amount
    ON bounty(amount_minor DESC, id DESC);
-- Per-repo capping.
CREATE INDEX IF NOT EXISTS bounty_repo ON bounty(repo);
-- Filtering by what you have already decided.
CREATE INDEX IF NOT EXISTS triage_status ON triage(status);

-- Text filtering over the two fields worth searching. External content, so
-- the issue bodies are not stored twice.
CREATE VIRTUAL TABLE IF NOT EXISTS bounty_fts USING fts5(
    title,
    repo,
    content='bounty',
    content_rowid='id',
    tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS bounty_fts_insert AFTER INSERT ON bounty BEGIN
    INSERT INTO bounty_fts(rowid, title, repo) VALUES (new.id, new.title, new.repo);
END;

CREATE TRIGGER IF NOT EXISTS bounty_fts_delete AFTER DELETE ON bounty BEGIN
    INSERT INTO bounty_fts(bounty_fts, rowid, title, repo)
        VALUES ('delete', old.id, old.title, old.repo);
END;

CREATE TRIGGER IF NOT EXISTS bounty_fts_update AFTER UPDATE ON bounty BEGIN
    INSERT INTO bounty_fts(bounty_fts, rowid, title, repo)
        VALUES ('delete', old.id, old.title, old.repo);
    INSERT INTO bounty_fts(rowid, title, repo) VALUES (new.id, new.title, new.repo);
END;
