"""The application factory.

Everything the application needs is handed to it. It opens no database, reads no
configuration file and consults no environment, which is what lets a test build
one over a temporary corpus in a line and the launcher build the real one over
the real corpus in another.

That includes the built interface: where it is on disk is the launcher's
business, and an application without one is still the whole API.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from .. import __version__
from ..config import ScanSettings
from ..domain.scoring import ScoreWeights
from ..store.db import Database
from .routes import bounties, meta, scan, triage
from .scan import ScanSupervisor, Sweep
from .state import AppState, Clock, utc_now
from .static import interface_files

API_PREFIX = "/api"


def create_app(
    db: Database,
    *,
    weights: ScoreWeights | None = None,
    settings: ScanSettings | None = None,
    token: str | None = None,
    clock: Clock = utc_now,
    sweep: Sweep | None = None,
    interface: Path | None = None,
) -> FastAPI:
    """Build the application over an open corpus.

    Given a built interface, serve it too. Without one this is the API alone,
    which is what the tests and the development server want.
    """
    supervisor = ScanSupervisor(
        db,
        settings=settings or ScanSettings(),
        weights=weights or ScoreWeights(),
        token=token,
        sweep=sweep,
    )
    state = AppState(
        db=db, weights=weights or ScoreWeights(), scans=supervisor, clock=clock
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        # A sweep left running would keep the process alive after the window is
        # closed. What it has written already stands, and the run stays
        # resumable, so cancelling it costs nothing.
        await supervisor.stop()

    app = FastAPI(
        title="bounty-searcher",
        version=__version__,
        summary="The corpus, and what you have decided about it.",
        lifespan=lifespan,
    )
    app.state.app = state

    for router in (bounties.router, triage.router, scan.router, meta.router):
        app.include_router(router, prefix=API_PREFIX)

    # Mounted last and at the root, so it is reached only by a request no route
    # above it claimed.
    if interface is not None:
        app.mount("/", interface_files(interface), name="interface")

    return app
