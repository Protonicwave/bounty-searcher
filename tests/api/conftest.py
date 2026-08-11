"""One application over one temporary corpus, with the clock held still.

Every test scores, filters and ages against the moment the corpus was built for,
so a test that passes today passes in a year.

The client talks to the application in process and on the test's own event loop.
That is what lets a test read the progress stream as it arrives rather than after
it has finished, and it is the same single-threaded arrangement the application
runs in for real.
"""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx
import pytest

from bounty_searcher.api.app import create_app
from bounty_searcher.api.scan import Sweep
from bounty_searcher.config import ScanSettings
from bounty_searcher.store.db import Database
from tests.store.corpus import NOW, WEIGHTS


@dataclass(frozen=True, slots=True)
class Harness:
    """A client, and the connection to fill the corpus it reads."""

    client: httpx.AsyncClient
    conn: sqlite3.Connection


class Build(Protocol):
    async def __call__(
        self, *, sweep: Sweep | None = None, settings: ScanSettings | None = None
    ) -> Harness: ...


@pytest.fixture
async def build(tmp_path: Path) -> AsyncIterator[Build]:
    """Build an application, optionally with a stand-in sweep."""
    async with AsyncExitStack() as stack:

        async def make(
            *, sweep: Sweep | None = None, settings: ScanSettings | None = None
        ) -> Harness:
            db = stack.enter_context(Database(tmp_path / "state.db"))
            app = create_app(
                db,
                weights=WEIGHTS,
                settings=settings or ScanSettings(),
                clock=lambda: NOW,
                sweep=sweep,
            )
            # Run the lifespan, so shutdown cancels any sweep still going.
            await stack.enter_async_context(app.router.lifespan_context(app))
            client = await stack.enter_async_context(
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app), base_url="http://corpus"
                )
            )
            return Harness(client, db.conn)

        yield make


@pytest.fixture
async def api(build: Build) -> Harness:
    """The common case: an application with nothing stubbed out."""
    return await build()
