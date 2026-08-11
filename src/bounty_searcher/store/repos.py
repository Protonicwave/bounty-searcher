"""Repository facts, and which repositories are worth polling directly.

The watchlist is derived rather than kept. A repository earns its place by
having paid before or by holding something you shortlisted, both of which the
corpus already knows, so there is no list to maintain and it improves on its
own as you triage.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from ..domain.models import Repository, TriageStatus
from .db import to_ts

# Language and star count do not move fast enough to matter for scoring.
REPO_META_TTL = timedelta(days=7)

# Statuses that say you are interested in a repository, not just aware of it.
COMMITTED = (TriageStatus.SHORTLISTED, TriageStatus.APPLIED)


def _repo_from_row(row: sqlite3.Row) -> Repository:
    return Repository(
        name=row["name"],
        language=row["language"],
        stars=row["stars"],
        archived=bool(row["archived"]),
        is_fork=bool(row["is_fork"]),
    )


def get_meta(
    conn: sqlite3.Connection, names: list[str], now: datetime
) -> dict[str, Repository]:
    """The facts we already hold and still trust, for the repositories asked about.

    Anything missing from the result is a repository the caller has to fetch.
    """
    if not names:
        return {}
    placeholders = ", ".join("?" * len(names))
    rows = conn.execute(
        "SELECT * FROM repo_meta"  # noqa: S608 - placeholders only
        f" WHERE name IN ({placeholders}) AND fetched_at >= ?",
        [*names, to_ts(now - REPO_META_TTL)],
    )
    return {row["name"]: _repo_from_row(row) for row in rows}


def put_meta(conn: sqlite3.Connection, repos: list[Repository], now: datetime) -> None:
    stamp = to_ts(now)
    conn.execute("BEGIN")
    try:
        conn.executemany(
            """
            INSERT INTO repo_meta (name, language, stars, archived, is_fork,
                                   fetched_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (name) DO UPDATE SET
                language = excluded.language,
                stars = excluded.stars,
                archived = excluded.archived,
                is_fork = excluded.is_fork,
                fetched_at = excluded.fetched_at
            """,
            [
                (
                    repo.name,
                    repo.language,
                    repo.stars,
                    int(repo.archived),
                    int(repo.is_fork),
                    stamp,
                )
                for repo in repos
            ],
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


_WATCHLIST = f"""
SELECT b.repo AS repo, MAX(b.last_seen_at) AS seen
FROM bounty b
LEFT JOIN bounty_score s ON s.bounty_id = b.id
LEFT JOIN triage t ON t.bounty_id = b.id
WHERE (b.amount_minor IS NOT NULL AND s.suspect_reason IS NULL)
   OR t.status IN ({", ".join("?" * len(COMMITTED))})
GROUP BY b.repo
ORDER BY seen DESC
LIMIT ?
"""


def watchlist(
    conn: sqlite3.Connection, seed: tuple[str, ...] = (), limit: int = 200
) -> list[str]:
    """Repositories worth polling, the configured ones first.

    Ordered by how recently we saw anything from them, so a limit trims the
    ones that have gone quiet rather than an arbitrary slice.
    """
    found = list(seed)
    known = set(seed)
    for row in conn.execute(_WATCHLIST, [*(s.value for s in COMMITTED), limit]):
        if row["repo"] not in known:
            known.add(row["repo"])
            found.append(row["repo"])
    return found
