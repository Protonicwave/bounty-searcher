"""Bookkeeping for scans: one row per run, one per query within it.

Recording each query as it completes is what makes an interrupted sweep
resumable, and holding its yield beside its cost is what makes it visible which
queries actually earn their quota.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .db import from_ts, to_ts


class RunStatus(StrEnum):
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class QueryStatus(StrEnum):
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ScanRun:
    id: int
    started_at: datetime
    finished_at: datetime | None
    status: RunStatus
    planned_queries: int
    error: str | None


def start_run(conn: sqlite3.Connection, now: datetime, planned_queries: int) -> int:
    cursor = conn.execute(
        "INSERT INTO scan_run (started_at, status, planned_queries) VALUES (?, ?, ?)",
        (to_ts(now), RunStatus.RUNNING.value, planned_queries),
    )
    return int(cursor.lastrowid or 0)


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    now: datetime,
    status: RunStatus,
    error: str | None = None,
) -> None:
    conn.execute(
        "UPDATE scan_run SET finished_at = ?, status = ?, error = ? WHERE id = ?",
        (to_ts(now), status.value, error, run_id),
    )


def set_planned(conn: sqlite3.Connection, run_id: int, planned: int) -> None:
    """Correct the plan size. A saturated query adds work after the start."""
    conn.execute(
        "UPDATE scan_run SET planned_queries = ? WHERE id = ?", (planned, run_id)
    )


def _run_from_row(row: sqlite3.Row) -> ScanRun:
    return ScanRun(
        id=row["id"],
        started_at=from_ts(row["started_at"]),
        finished_at=(
            from_ts(row["finished_at"]) if row["finished_at"] is not None else None
        ),
        status=RunStatus(row["status"]),
        planned_queries=row["planned_queries"],
        error=row["error"],
    )


def get_run(conn: sqlite3.Connection, run_id: int) -> ScanRun | None:
    row = conn.execute("SELECT * FROM scan_run WHERE id = ?", (run_id,)).fetchone()
    return None if row is None else _run_from_row(row)


def latest_run(conn: sqlite3.Connection) -> ScanRun | None:
    """The most recently started run, for the status line."""
    row = conn.execute("SELECT * FROM scan_run ORDER BY id DESC LIMIT 1").fetchone()
    return None if row is None else _run_from_row(row)


def last_completed_run(conn: sqlite3.Connection) -> ScanRun | None:
    """The most recent run that finished cleanly.

    What "new" and "changed" are measured against. A run that failed or was
    interrupted covered an unknown fraction of the plan, so comparing against
    it would mark an arbitrary slice of the corpus as fresh.
    """
    row = conn.execute(
        "SELECT * FROM scan_run WHERE status = ? ORDER BY id DESC LIMIT 1",
        (RunStatus.DONE.value,),
    ).fetchone()
    return None if row is None else _run_from_row(row)


def start_query(
    conn: sqlite3.Connection, run_id: int, source: str, query: str, now: datetime
) -> int:
    """Claim a query for a run. Re-claiming one resets it to running."""
    cursor = conn.execute(
        """
        INSERT INTO scan_query (run_id, source, query, status, started_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (run_id, source, query) DO UPDATE SET
            status = excluded.status,
            started_at = excluded.started_at,
            finished_at = NULL,
            error = NULL
        RETURNING id
        """,
        (run_id, source, query, QueryStatus.RUNNING.value, to_ts(now)),
    )
    return int(cursor.fetchone()["id"])


def finish_query(
    conn: sqlite3.Connection,
    query_id: int,
    now: datetime,
    *,
    results: int = 0,
    new_bounties: int = 0,
    error: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE scan_query
        SET finished_at = ?, status = ?, results = ?, new_bounties = ?, error = ?
        WHERE id = ?
        """,
        (
            to_ts(now),
            (QueryStatus.FAILED if error else QueryStatus.DONE).value,
            results,
            new_bounties,
            error,
            query_id,
        ),
    )


def completed_queries(conn: sqlite3.Connection, run_id: int) -> set[tuple[str, str]]:
    """The (source, query) pairs this run has already finished.

    A resumed sweep skips these, so it continues rather than restarts.
    """
    return {
        (row["source"], row["query"])
        for row in conn.execute(
            "SELECT source, query FROM scan_query WHERE run_id = ? AND status = ?",
            (run_id, QueryStatus.DONE.value),
        )
    }


def resumable_run(conn: sqlite3.Connection) -> ScanRun | None:
    """A run that was left unfinished, if there is one to pick up."""
    row = conn.execute(
        "SELECT * FROM scan_run WHERE status = ? ORDER BY id DESC LIMIT 1",
        (RunStatus.RUNNING.value,),
    ).fetchone()
    return None if row is None else _run_from_row(row)
