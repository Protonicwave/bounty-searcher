"""Running one sweep in the background, and telling everyone watching.

A scan is a single long job, so the supervisor holds at most one. Progress is
broadcast to whoever is listening rather than polled for, and the last event is
kept so a browser that connects halfway through sees where the sweep is instead
of waiting for the next query to finish.

Nothing here survives a restart, and it does not need to: a restart kills the
sweep too, so there is nothing left to stream. What did happen is in the corpus,
which is what the metadata route reads.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime

from ..config import ScanSettings
from ..domain.scoring import ScoreWeights
from ..scan.planner import Planner
from ..scan.runner import ProgressHook, ScanOutcome, ScanProgress, StartHook, run_scan
from ..scan.sources import build_sources
from ..sources.github.client import GitHubClient
from ..sources.github.quota import QuotaSnapshot
from ..store.db import Database
from ..store.http_cache import load_etags, save_etags

log = logging.getLogger(__name__)

# One sweep, one function. Injected so the supervisor's own behaviour, which is
# concurrency and broadcasting, can be tested without a network.
type Sweep = Callable[[datetime, StartHook, ProgressHook], Awaitable[ScanOutcome]]


class ScanBusy(RuntimeError):
    """A sweep is already running. Two at once would fight over the quota."""


def _log_outcome(task: asyncio.Task[ScanOutcome]) -> None:
    """Collect how a sweep ended, whatever that was."""
    if task.cancelled():
        log.info("scan cancelled")
        return
    if (error := task.exception()) is not None:
        log.error("scan failed: %s", error)
        return
    outcome = task.result()
    log.info(
        "scan %d finished: %d/%d queries, %d new",
        outcome.run_id,
        outcome.completed,
        outcome.planned,
        outcome.inserted,
    )


class ScanSupervisor:
    """The one background sweep, and the subscribers watching it."""

    def __init__(
        self,
        db: Database,
        *,
        settings: ScanSettings,
        weights: ScoreWeights,
        token: str | None = None,
        sweep: Sweep | None = None,
    ) -> None:
        self._db = db
        self._settings = settings
        self._weights = weights
        self._token = token
        self._sweep = sweep or self._github_sweep
        self._task: asyncio.Task[ScanOutcome] | None = None
        self._subscribers: set[asyncio.Queue[ScanProgress | None]] = set()
        self._latest: ScanProgress | None = None
        self._quota: QuotaSnapshot | None = None
        self.run_id: int | None = None

    # -- state -------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def quota(self) -> QuotaSnapshot | None:
        """The last thing GitHub said about the budgets, if anything has.

        None until a sweep has been run in this process. Guessing would be
        worse than admitting the number is not known.
        """
        return self._quota

    def latest(self) -> ScanProgress | None:
        return self._latest

    # -- running -----------------------------------------------------------

    async def start(self, now: datetime) -> tuple[int, bool]:
        """Start a sweep and return its run id, and whether it resumed one.

        Returns once the run has an identity, which is before any request goes
        out, so the caller gets an answer immediately rather than in an hour.
        """
        if self.running:
            raise ScanBusy("a scan is already running")

        loop = asyncio.get_running_loop()
        started: asyncio.Future[tuple[int, bool]] = loop.create_future()

        def on_start(run_id: int, resumed: bool) -> None:
            self.run_id = run_id
            if not started.done():
                started.set_result((run_id, resumed))

        self._latest = None
        self._task = asyncio.create_task(self._supervise(now, on_start))
        # Nobody awaits the task once this call has its run id, so whatever it
        # ends with has to be collected here or the loop complains at collection
        # time about an exception nothing retrieved.
        self._task.add_done_callback(_log_outcome)

        # If the sweep fails before it opens a run, fail the wait with it rather
        # than hanging on a future nobody will ever resolve.
        done, _ = await asyncio.wait(
            (started, self._task), return_when=asyncio.FIRST_COMPLETED
        )
        if started in done:
            return started.result()
        await self._task  # raises whatever went wrong
        # It finished cleanly without ever opening a run, which a real sweep
        # cannot do. Not a conflict: something is wrong with the sweep itself.
        raise RuntimeError("the scan ended before it opened a run")

    async def stop(self) -> None:
        """Cancel a running sweep and wait for it to put itself away."""
        if self._task is None or self._task.done():
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            log.debug("scan cancelled during shutdown")
        except Exception:
            log.exception("scan failed during shutdown")

    async def _supervise(self, now: datetime, on_start: StartHook) -> ScanOutcome:
        try:
            return await self._sweep(now, on_start, self._publish)
        finally:
            self._close_subscribers()

    async def _github_sweep(
        self, now: datetime, on_start: StartHook, on_progress: ProgressHook
    ) -> ScanOutcome:
        """The real thing: open a client, plan, run, and keep the ETags."""
        planner = Planner(self._settings, now.date())
        etags = load_etags(self._db.conn)

        async with GitHubClient(
            self._token, concurrency=self._settings.workers, etags=etags
        ) as client:
            self._quota = client.governor.snapshot()
            sources, cost = build_sources(client, self._db, self._settings, planner)
            log.info("planned %d requests across %d sources", cost, len(sources))

            try:
                return await run_scan(
                    self._db,
                    client,
                    sources,
                    weights=self._weights,
                    now=now,
                    planner=planner,
                    workers=self._settings.workers,
                    on_progress=on_progress,
                    on_start=on_start,
                )
            finally:
                self._quota = client.governor.snapshot()
                save_etags(self._db.conn, client.etags, now)

    # -- broadcasting ------------------------------------------------------

    def _publish(self, event: ScanProgress) -> None:
        self._latest = event
        for queue in self._subscribers:
            queue.put_nowait(event)

    def _close_subscribers(self) -> None:
        for queue in self._subscribers:
            queue.put_nowait(None)

    async def events(self) -> AsyncIterator[ScanProgress]:
        """Every query this sweep finishes from now until it stops.

        A subscriber that arrives late is given the most recent event first, so
        a reconnecting browser draws the right progress straight away.
        """
        if not self.running:
            return

        queue: asyncio.Queue[ScanProgress | None] = asyncio.Queue()
        self._subscribers.add(queue)
        try:
            if (latest := self._latest) is not None:
                yield latest
            while (event := await queue.get()) is not None:
                yield event
        finally:
            self._subscribers.discard(queue)
