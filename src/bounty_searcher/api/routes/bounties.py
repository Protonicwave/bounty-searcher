"""Reading the corpus: one page at a time, or one bounty in full.

Every filter and every ordering decision is passed to SQLite, which returns
exactly the rows asked for. Nothing here loops over the corpus.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from ...domain.models import TriageStatus
from ...domain.scoring import component_maxima
from ...store import bounties as store_bounties
from ...store import scans, views
from ...store.bounties import BountyFilter, Cursor, SortKey
from ..schemas import BountyDetail, BountyPage, detail_out, row_out
from ..state import AppState, Now, State

router = APIRouter(tags=["bounties"])

# A page has to be big enough to fill a tall window and prime the next scroll,
# and small enough that the request stays inside its latency budget.
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def _narrow(
    view: views.View,
    *,
    language: str | None,
    min_amount_minor: int | None,
    min_stars: int | None,
    max_age_days: float | None,
    min_score: float | None,
    statuses: list[TriageStatus] | None,
    q: str | None,
    include_suspect: bool | None,
    include_claimed: bool | None,
) -> BountyFilter:
    """The view's filter with any explicitly given parameter applied over it.

    A view is a starting point rather than a cage: the interface layers the
    filter chips in the status line on top of whichever view is selected, and an
    omitted parameter leaves the view's own answer alone.
    """
    base = view.filters
    return replace(
        base,
        language=_or(language, base.language),
        min_amount_minor=_or(min_amount_minor, base.min_amount_minor),
        min_stars=_or(min_stars, base.min_stars),
        max_age_days=_or(max_age_days, base.max_age_days),
        min_score=_or(min_score, base.min_score),
        text=_or(q, base.text),
        statuses=tuple(statuses) if statuses else base.statuses,
        include_suspect=_or(include_suspect, base.include_suspect),
        include_claimed=_or(include_claimed, base.include_claimed),
    )


def _or[T](given: T | None, fallback: T) -> T:
    """The parameter if it was given, and the view's answer if it was not."""
    return fallback if given is None else given


@router.get("/bounties", response_model=BountyPage)
async def list_bounties(
    state: State,
    now: Now,
    view: views.ViewName = views.ViewName.ALL,
    sort: SortKey | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    language: str | None = None,
    min_amount_minor: Annotated[int | None, Query(ge=0)] = None,
    min_stars: Annotated[int | None, Query(ge=0)] = None,
    max_age_days: Annotated[float | None, Query(gt=0)] = None,
    min_score: float | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    statuses: Annotated[list[TriageStatus] | None, Query()] = None,
    include_suspect: bool | None = None,
    include_claimed: bool | None = None,
) -> BountyPage:
    """One page of the corpus under a saved view, narrowed by any parameter."""
    conn = state.db.conn
    since = _since(state)
    resolved = views.build(view, last_scan_started=since)
    filters = _narrow(
        resolved,
        language=language,
        min_amount_minor=min_amount_minor,
        min_stars=min_stars,
        max_age_days=max_age_days,
        min_score=min_score,
        statuses=statuses,
        q=q,
        include_suspect=include_suspect,
        include_claimed=include_claimed,
    )
    order = sort or resolved.sort

    page = store_bounties.list_bounties(
        conn,
        as_of=now,
        filters=filters,
        sort=order,
        cursor=_cursor(cursor),
        limit=limit,
    )
    maxima = component_maxima(state.weights)

    return BountyPage(
        rows=[row_out(row, maxima=maxima, as_of=now, since=since) for row in page.rows],
        total=page.total,
        next_cursor=page.next_cursor.encode() if page.next_cursor else None,
        view=view,
        sort=order,
    )


@router.get(
    "/bounties/{bounty_id}",
    response_model=BountyDetail,
    responses={status.HTTP_404_NOT_FOUND: {"description": "No such bounty"}},
)
async def get_bounty(state: State, now: Now, bounty_id: int) -> BountyDetail:
    """One bounty in full: body, breakdown, and where the figure came from."""
    scored = store_bounties.get(state.db.conn, bounty_id)
    if scored is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such bounty")
    return detail_out(
        scored,
        maxima=component_maxima(state.weights),
        as_of=now,
        since=_since(state),
    )


def _cursor(token: str | None) -> Cursor | None:
    """Decode a page cursor. A corrupt one is the caller's mistake, not a 500."""
    if not token:
        return None
    try:
        return Cursor.decode(token)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "malformed cursor"
        ) from exc


def _since(state: AppState) -> datetime | None:
    """When the last clean sweep began, which is what new and changed mean."""
    run = scans.last_completed_run(state.db.conn)
    return None if run is None else run.started_at
