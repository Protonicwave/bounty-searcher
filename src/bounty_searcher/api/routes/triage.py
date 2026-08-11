"""Deciding about a bounty, and taking the decision back.

Every transition returns the token that reverses it, so the interface can offer
undo without remembering what the previous state was. Several ids under one
request share one token, which is what holding the dismiss key needs.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException, status

from ...store import triage as store_triage
from ..schemas import TriageRequest, TriageResult, UndoRequest, UndoResult
from ..state import Now, State

router = APIRouter(prefix="/triage", tags=["triage"])


def _missing(conn: sqlite3.Connection, bounty_ids: list[int]) -> list[int]:
    """Which of these ids the corpus does not hold."""
    placeholders = ", ".join("?" * len(bounty_ids))
    found = {
        row["id"]
        for row in conn.execute(
            f"SELECT id FROM bounty WHERE id IN ({placeholders})",  # noqa: S608
            bounty_ids,
        )
    }
    return [bounty_id for bounty_id in bounty_ids if bounty_id not in found]


@router.post("", response_model=TriageResult)
async def apply(state: State, now: Now, request: TriageRequest) -> TriageResult:
    """Move bounties to a status, and return the token that undoes it."""
    conn = state.db.conn
    # Checked here rather than left to the foreign key, so an id the interface
    # has gone stale on reads as a 404 and not as a failed write.
    if missing := _missing(conn, request.bounty_ids):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"no such bounty: {', '.join(str(i) for i in missing)}",
        )

    token = store_triage.set_status(
        conn,
        request.bounty_ids,
        request.status,
        now,
        snooze_until=request.snooze_until,
    )
    return TriageResult(
        bounty_ids=request.bounty_ids, status=request.status, undo_token=token
    )


@router.post("/undo", response_model=UndoResult)
async def undo(state: State, now: Now, request: UndoRequest) -> UndoResult:
    """Reverse a transition, or the most recent one if no token is given.

    Undoing something already undone restores nothing rather than failing, so a
    keystroke repeated on a slow connection cannot double-apply.
    """
    conn = state.db.conn
    if request.undo_token is None:
        restored = store_triage.undo_last(conn, now)
    else:
        restored = store_triage.undo(conn, request.undo_token, now)
    return UndoResult(bounty_ids=restored)
