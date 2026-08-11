"""State for the original CLI: issues already shown, plus a repo cache.

The "seen" table is what makes `--new-only` work. On a schedule, that is the
difference between re-reading the same 200 issues every morning and getting the
handful that appeared overnight.

The corpus replaces both of these. This module stays until the CLI is moved
onto it, and then it goes.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from types import TracebackType
from typing import Any

from ..domain.models import ScoredBounty
from .db import connect, migrate

REPO_CACHE_TTL = 7 * 86400  # language and star count don't move fast

# Cached rows missing any of these were written by an older version and get
# refetched rather than silently scoring against absent fields.
REPO_CACHE_FIELDS = ("language", "stars", "archived", "fork")


class Store:
    def __init__(self, path: Path | str | None = None) -> None:
        self.conn: sqlite3.Connection = connect(path)
        self.path = path
        migrate(self.conn)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- seen tracking -----------------------------------------------------

    def known_keys(self) -> set[str]:
        return {row["key"] for row in self.conn.execute("SELECT key FROM seen")}

    def record(self, bounties: list[ScoredBounty]) -> None:
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
                (
                    s.bounty.key,
                    s.bounty.repo,
                    s.bounty.number,
                    s.bounty.title,
                    s.bounty.url,
                    float(s.bounty.amount.units) if s.bounty.amount else None,
                    s.score.total,
                    now,
                    now,
                )
                for s in bounties
            ],
        )

    def forget_all(self) -> int:
        cur = self.conn.execute("DELETE FROM seen")
        return cur.rowcount

    # -- repo cache --------------------------------------------------------

    def get_repo(self, name: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT data, fetched_at FROM repo_cache WHERE name = ?", (name,)
        ).fetchone()
        if row is None or time.time() - row["fetched_at"] > REPO_CACHE_TTL:
            return None
        data: dict[str, Any] = json.loads(row["data"])
        if any(field not in data for field in REPO_CACHE_FIELDS):
            return None
        return data

    def put_repo(self, name: str, data: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO repo_cache (name, data, fetched_at)"
            " VALUES (?, ?, ?)",
            (name, json.dumps(data), time.time()),
        )
