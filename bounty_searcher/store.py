"""SQLite state: which bounties you've already seen, plus a repo metadata cache.

The "seen" table is what makes `--new-only` work -- on a schedule, that's the
difference between re-reading the same 200 issues every morning and getting
the handful that appeared overnight.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from .models import Bounty

REPO_CACHE_TTL = 7 * 86400  # language and star count don't move fast

# Cached rows missing any of these were written by an older version and get
# refetched rather than silently scoring against absent fields.
REPO_CACHE_FIELDS = ("language", "stars", "archived", "fork")

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
    key         TEXT PRIMARY KEY,
    repo        TEXT NOT NULL,
    number      INTEGER NOT NULL,
    title       TEXT,
    url         TEXT,
    amount      REAL,
    score       REAL,
    first_seen  REAL NOT NULL,
    last_seen   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS repo_cache (
    name        TEXT PRIMARY KEY,
    data        TEXT NOT NULL,
    fetched_at  REAL NOT NULL
);
"""


def default_db_path() -> Path:
    return Path.home() / ".bounty-searcher" / "state.db"


class Store:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- seen tracking -----------------------------------------------------

    def known_keys(self) -> set[str]:
        return {row["key"] for row in self.conn.execute("SELECT key FROM seen")}

    def record(self, bounties: list[Bounty]) -> None:
        now = time.time()
        self.conn.executemany(
            """
            INSERT INTO seen (key, repo, number, title, url, amount, score,
                              first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                last_seen = excluded.last_seen,
                score     = excluded.score,
                amount    = excluded.amount
            """,
            [
                (b.key, b.repo, b.number, b.title, b.url, b.amount, b.score, now, now)
                for b in bounties
            ],
        )
        self.conn.commit()

    def forget_all(self) -> int:
        cur = self.conn.execute("DELETE FROM seen")
        self.conn.commit()
        return cur.rowcount

    # -- repo cache --------------------------------------------------------

    def get_repo(self, name: str) -> dict | None:
        row = self.conn.execute(
            "SELECT data, fetched_at FROM repo_cache WHERE name = ?", (name,)
        ).fetchone()
        if row is None or time.time() - row["fetched_at"] > REPO_CACHE_TTL:
            return None
        data = json.loads(row["data"])
        if any(field not in data for field in REPO_CACHE_FIELDS):
            return None
        return data

    def put_repo(self, name: str, data: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO repo_cache (name, data, fetched_at) VALUES (?, ?, ?)",
            (name, json.dumps(data), time.time()),
        )
        self.conn.commit()
