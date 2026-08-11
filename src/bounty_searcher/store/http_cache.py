"""Entity tags, carried between runs.

The client keeps its tags in a plain dictionary because it has no business
knowing there is a database. This is the pair of functions that fills it at the
start of a sweep and writes it back at the end.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from .db import to_ts


def load_etags(conn: sqlite3.Connection) -> dict[str, str]:
    return {row["url"]: row["etag"] for row in conn.execute("SELECT * FROM http_etag")}


def save_etags(conn: sqlite3.Connection, etags: dict[str, str], now: datetime) -> None:
    stamp = to_ts(now)
    conn.execute("BEGIN")
    try:
        conn.executemany(
            """
            INSERT INTO http_etag (url, etag, updated_at) VALUES (?, ?, ?)
            ON CONFLICT (url) DO UPDATE SET
                etag = excluded.etag,
                updated_at = excluded.updated_at
            """,
            [(url, etag, stamp) for url, etag in etags.items()],
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
