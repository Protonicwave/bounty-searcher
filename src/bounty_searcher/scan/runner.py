"""Running a sweep: workers, writes, resumption and progress.

The runner owns everything the sources deliberately do not. It decides how many
queries run at once, when a saturated query earns follow-ups, what gets written
and when, and how an interrupted sweep picks up. A source only has to fetch.

Writes happen on the event loop between awaits, so they need no lock: SQLite is
only ever touched from one place at one time here, and a batch of a hundred
rows takes milliseconds. Each query is written as it finishes rather than at
the end, which is what makes an interrupted sweep worth resuming.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from ..domain.models import Bounty, Repository
from ..domain.scoring import ScoreWeights
from ..sources.base import Source, SourceQuery, SourceResult
from ..sources.github.client import GitHubClient
from ..sources.github.repos import fetch_repo
from ..store import bounties as store_bounties
from ..store import repos as store_repos
from ..store import scans
from ..store.db import Database
from .planner import PlannedQuery, Planner

log = logging.getLogger(__name__)

DEFAULT_WORKERS = 6


@dataclass(frozen=True, slots=True)
class ScanProgress:
    """One query finished. Everything the interface draws comes from these."""

    run_id: int
    completed: int
    planned: int
    source: str
    query: str
    results: int
    new_bounties: int
    requests: int
    error: str | None = None


type ProgressHook = Callable[[ScanProgress], None]


@dataclass(frozen=True, slots=True)
class ScanOutcome:
    run_id: int
    planned: int
    completed: int
    failed: int
    found: int
    inserted: int
    changed: int
    requests: int
    resumed: bool = False


class RepoEnricher:
    """Language and stars for the repositories a sweep turns up.

    Search results carry neither, and the scorer needs both. Every repository
    is fetched at most once per sweep however many queries find it, and the
    result is cached for a week, so the second night costs almost nothing.
    """

    def __init__(self, client: GitHubClient, database: Database, now: datetime) -> None:
        self._client = client
        self._db = database
        self._now = now
        self._known: dict[str, Repository | None] = {}
        self._pending: dict[str, asyncio.Task[Repository | None]] = {}

    async def apply(self, found: Sequence[Bounty]) -> tuple[list[Bounty], int]:
        """Copy repository facts onto each bounty. Returns them and the cost."""
        names = {bounty.repo for bounty in found}
        requests = await self._resolve(sorted(names))

        enriched = []
        for bounty in found:
            repo = self._known.get(bounty.repo)
            enriched.append(bounty if repo is None else _with_repo(bounty, repo))
        return enriched, requests

    async def _resolve(self, names: list[str]) -> int:
        wanted = [name for name in names if name not in self._known]
        if not wanted:
            return 0

        cached = store_repos.get_meta(self._db.conn, wanted, self._now)
        self._known.update(cached)

        missing = [name for name in wanted if name not in cached]
        if not missing:
            return 0

        fetched = await asyncio.gather(*(self._fetch(name) for name in missing))
        found = [repo for repo in fetched if repo is not None]
        if found:
            store_repos.put_meta(self._db.conn, found, self._now)
        return len(missing)

    async def _fetch(self, name: str) -> Repository | None:
        """Fetch one repository, sharing the request if it is already in flight."""
        if name in self._known:
            return self._known[name]
        task = self._pending.get(name)
        if task is None:
            task = asyncio.create_task(fetch_repo(self._client, name))
            self._pending[name] = task
        repo = await task
        self._pending.pop(name, None)
        self._known[name] = repo
        return repo


def _with_repo(bounty: Bounty, repo: Repository) -> Bounty:
    # An archived repository will not merge anything, so it counts as taken.
    claim_reason = "repo archived" if repo.archived else bounty.claim_reason
    return replace(
        bounty,
        language=repo.language,
        stars=repo.stars,
        is_fork=repo.is_fork,
        claim_reason=claim_reason,
    )


class _Sweep:
    """One run, from the plan to the last write."""

    def __init__(
        self,
        database: Database,
        client: GitHubClient,
        sources: Sequence[Source],
        *,
        weights: ScoreWeights,
        now: datetime,
        planner: Planner | None,
        on_progress: ProgressHook | None,
    ) -> None:
        self._db = database
        self._sources = {source.name: source for source in sources}
        self._weights = weights
        self._now = now
        self._planner = planner
        self._on_progress = on_progress
        self._enricher = RepoEnricher(client, database, now)
        self._queue: asyncio.Queue[SourceQuery] = asyncio.Queue()
        # Search queries by the string they were planned with, so a saturated
        # result can be handed back to the planner to be split.
        self._planned: dict[str, PlannedQuery] = {}

        self.run_id = 0
        self.planned = 0
        self.completed = 0
        self.failed = 0
        self.found = 0
        self.inserted = 0
        self.changed = 0
        self.requests = 0

    def enqueue(self, query: SourceQuery) -> None:
        self._queue.put_nowait(query)
        self.planned += 1

    def remember(self, planned: Sequence[PlannedQuery]) -> None:
        for query in planned:
            self._planned[query.as_source_query().key] = query

    async def work(self) -> None:
        while True:
            try:
                query = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                await self._run_one(query)
            finally:
                self._queue.task_done()

    async def _run_one(self, query: SourceQuery) -> None:
        source = self._sources[query.source]
        query_id = scans.start_query(
            self._db.conn, self.run_id, query.source, query.key, self._now
        )

        result = await source.fetch(query)
        enriched, lookups = await self._enricher.apply(result.bounties)
        written = self._write(enriched)
        self.requests += result.requests + lookups

        scans.finish_query(
            self._db.conn,
            query_id,
            self._now,
            results=len(result.bounties),
            new_bounties=written,
            error=result.error,
        )

        self.completed += 1
        if result.error:
            self.failed += 1
        self.found += len(result.bounties)
        self._split_if_saturated(result)
        self._report(query, result, written)

    def _write(self, found: list[Bounty]) -> int:
        """Store one query's results and score them. Returns how many are new."""
        if not found:
            return 0
        result = store_bounties.upsert_many(self._db.conn, found, self._now)
        store_bounties.score_bounties(
            self._db.conn, self._weights, self._now, bounty_ids=list(result.ids)
        )
        self.inserted += result.inserted
        self.changed += result.changed
        return result.inserted

    def _split_if_saturated(self, result: SourceResult) -> None:
        """Add the follow-up queries a saturated search has earned."""
        if not result.saturated or self._planner is None:
            return
        parent = self._planned.get(result.query.key)
        if parent is None:
            return
        refined = self._planner.refine(parent)
        self.remember(refined)
        for query in refined:
            self.enqueue(query.as_source_query())
        if refined:
            log.info("%s saturated, split into %d", result.query.key, len(refined))
            scans.set_planned(self._db.conn, self.run_id, self.planned)

    def _report(self, query: SourceQuery, result: SourceResult, written: int) -> None:
        if self._on_progress is None:
            return
        self._on_progress(
            ScanProgress(
                run_id=self.run_id,
                completed=self.completed,
                planned=self.planned,
                source=query.source,
                query=query.key,
                results=len(result.bounties),
                new_bounties=written,
                requests=result.requests,
                error=result.error,
            )
        )


async def run_scan(
    database: Database,
    client: GitHubClient,
    sources: Sequence[Source],
    *,
    weights: ScoreWeights,
    now: datetime,
    planner: Planner | None = None,
    workers: int = DEFAULT_WORKERS,
    resume: bool = True,
    on_progress: ProgressHook | None = None,
) -> ScanOutcome:
    """Run every source's plan, writing as it goes.

    A run left unfinished is picked up rather than started again: the queries
    it completed are recorded, so resuming re-runs only what is left. Set
    ``resume`` to False to start a fresh run regardless.
    """
    sweep = _Sweep(
        database,
        client,
        sources,
        weights=weights,
        now=now,
        planner=planner,
        on_progress=on_progress,
    )

    if planner is not None:
        sweep.remember(planner.plan())

    previous = scans.resumable_run(database.conn) if resume else None
    resumed = previous is not None
    sweep.run_id = (
        previous.id if previous is not None else scans.start_run(database.conn, now, 0)
    )
    done = scans.completed_queries(database.conn, sweep.run_id) if resumed else set()

    for source in sources:
        for query in source.plan():
            if (source.name, query.key) in done:
                continue
            sweep.enqueue(query)
    scans.set_planned(database.conn, sweep.run_id, sweep.planned)

    try:
        await asyncio.gather(*(sweep.work() for _ in range(max(1, workers))))
    except asyncio.CancelledError:
        # Everything written so far stands, and the run stays resumable.
        scans.finish_run(database.conn, sweep.run_id, now, scans.RunStatus.INTERRUPTED)
        raise
    except Exception as exc:
        scans.finish_run(
            database.conn, sweep.run_id, now, scans.RunStatus.FAILED, str(exc)
        )
        raise
    else:
        scans.finish_run(database.conn, sweep.run_id, now, scans.RunStatus.DONE)

    return ScanOutcome(
        run_id=sweep.run_id,
        planned=sweep.planned,
        completed=sweep.completed,
        failed=sweep.failed,
        found=sweep.found,
        inserted=sweep.inserted,
        changed=sweep.changed,
        requests=sweep.requests,
        resumed=resumed,
    )
