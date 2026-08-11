"""What the status line reads, and whether the process is alive.

One request rather than four. The status line shows corpus counts, the saved
views, the quota and the last scan together, so they are fetched together.
"""

from __future__ import annotations

from fastapi import APIRouter

from ... import __version__
from ...store import bounties as store_bounties
from ...store import scans, views
from ..schemas import (
    HealthOut,
    MetaOut,
    ScanOut,
    counts_out,
    quota_out,
    scan_out,
    view_out,
)
from ..state import Now, State

router = APIRouter(tags=["meta"])


@router.get("/meta", response_model=MetaOut)
async def meta(state: State, now: Now) -> MetaOut:
    """Corpus counts, the saved views, the quota, and the last scan."""
    conn = state.db.conn
    run = scans.latest_run(conn)
    last: ScanOut | None = None
    if run is not None:
        last = scan_out(
            run,
            scans.run_totals(conn, run.id),
            running=state.scans.running and state.scans.run_id == run.id,
        )

    return MetaOut(
        version=__version__,
        counts=counts_out(store_bounties.counts(conn, now)),
        views=[view_out(views.build(name)) for name in views.ViewName],
        last_scan=last,
        quota=quota_out(state.scans.quota()),
    )


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    """Alive, and which version. Reads nothing, so it cannot fail on the corpus."""
    return HealthOut(status="ok", version=__version__)
