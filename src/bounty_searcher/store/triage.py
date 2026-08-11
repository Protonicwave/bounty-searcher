"""Triage transitions, and the journal that makes them reversible.

Every transition is written to the journal before the state changes, so undo
replays a recorded fact rather than guessing what the previous state was. A run
of dismissals made in one gesture shares a batch token and comes back together.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from uuid import uuid4

from ..domain.models import Triage, TriageStatus
from .db import from_ts, to_ts


def get(conn: sqlite3.Connection, bounty_id: int) -> Triage:
    """The stored decision for a bounty. Untouched bounties are new."""
    row = conn.execute(
        "SELECT status, snooze_until, updated_at FROM triage WHERE bounty_id = ?",
        (bounty_id,),
    ).fetchone()
    if row is None:
        return Triage()
    return Triage(
        status=TriageStatus(row["status"]),
        snooze_until=(
            from_ts(row["snooze_until"]) if row["snooze_until"] is not None else None
        ),
        updated_at=from_ts(row["updated_at"]),
    )


def set_status(
    conn: sqlite3.Connection,
    bounty_ids: list[int],
    status: TriageStatus,
    now: datetime,
    *,
    snooze_until: datetime | None = None,
) -> str:
    """Move bounties to a status and return the token that undoes it.

    Passing several ids puts them under one token, which is what holding the
    dismiss key needs: one gesture, one undo.
    """
    batch = uuid4().hex
    stamp = to_ts(now)
    snooze = to_ts(snooze_until) if snooze_until is not None else None

    conn.execute("BEGIN")
    try:
        for bounty_id in bounty_ids:
            before = get(conn, bounty_id)
            conn.execute(
                """
                INSERT INTO triage_journal
                    (batch, bounty_id, from_status, from_snooze_until,
                     to_status, to_snooze_until, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch,
                    bounty_id,
                    before.status.value,
                    to_ts(before.snooze_until) if before.snooze_until else None,
                    status.value,
                    snooze,
                    stamp,
                ),
            )
            conn.execute(
                """
                INSERT INTO triage (bounty_id, status, snooze_until, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (bounty_id) DO UPDATE SET
                    status = excluded.status,
                    snooze_until = excluded.snooze_until,
                    updated_at = excluded.updated_at
                """,
                (bounty_id, status.value, snooze, stamp),
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return batch


def undo(conn: sqlite3.Connection, batch: str, now: datetime) -> list[int]:
    """Put a batch back the way it was. Returns the bounties restored.

    Undoing something already undone is a no-op rather than an error, so a
    keystroke repeated on a slow connection cannot double-apply.
    """
    entries = conn.execute(
        """
        SELECT bounty_id, from_status, from_snooze_until
        FROM triage_journal
        WHERE batch = ? AND undone_at IS NULL
        ORDER BY id DESC
        """,
        (batch,),
    ).fetchall()
    if not entries:
        return []

    stamp = to_ts(now)
    conn.execute("BEGIN")
    try:
        for entry in entries:
            conn.execute(
                """
                INSERT INTO triage (bounty_id, status, snooze_until, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (bounty_id) DO UPDATE SET
                    status = excluded.status,
                    snooze_until = excluded.snooze_until,
                    updated_at = excluded.updated_at
                """,
                (
                    entry["bounty_id"],
                    entry["from_status"],
                    entry["from_snooze_until"],
                    stamp,
                ),
            )
        conn.execute(
            "UPDATE triage_journal SET undone_at = ?"
            " WHERE batch = ? AND undone_at IS NULL",
            (stamp, batch),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return [entry["bounty_id"] for entry in entries]


def last_batch(conn: sqlite3.Connection) -> str | None:
    """The most recent transition that has not been undone."""
    row = conn.execute(
        "SELECT batch FROM triage_journal WHERE undone_at IS NULL"
        " ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return None if row is None else str(row["batch"])


def undo_last(conn: sqlite3.Connection, now: datetime) -> list[int]:
    batch = last_batch(conn)
    return [] if batch is None else undo(conn, batch, now)
