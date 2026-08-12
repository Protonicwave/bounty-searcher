"""A sweep end to end, against sources that never touch the network."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from datetime import date, timedelta
from pathlib import Path

import pytest
import respx

from bounty_searcher.domain.models import Bounty
from bounty_searcher.scan.planner import Planner
from bounty_searcher.scan.runner import (
    ProgressHook,
    ScanOutcome,
    ScanProgress,
    run_scan,
)
from bounty_searcher.sources.base import SourceQuery, SourceResult
from bounty_searcher.sources.github.client import GitHubClient
from bounty_searcher.store import scans
from bounty_searcher.store.bounties import BountyFilter, list_bounties
from bounty_searcher.store.db import Database
from tests.scan.test_planner import settings
from tests.sources.clock import FakeClock
from tests.sources.github.test_client import API, client
from tests.store.corpus import NOW, WEIGHTS, bounty

AS_OF = date(2026, 6, 1)
FAKE = "fake"


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Database]:
    with Database(tmp_path / "state.db") as db:
        yield db


@pytest.fixture
def gh() -> Iterator[GitHubClient]:
    """A client whose repository lookups all succeed."""
    with respx.mock:
        respx.get(url__regex=rf"{API}/repos/[^/]+/[^/]+$").respond(
            200, json={"language": "TypeScript", "stargazers_count": 500}
        )
        yield client(FakeClock())


class FakeSource:
    """Hands back whatever it was told to, and remembers what was asked."""

    def __init__(
        self,
        plan: Sequence[SourceQuery],
        results: dict[str, SourceResult] | None = None,
        *,
        name: str = FAKE,
    ) -> None:
        self.name = name
        self._plan = tuple(plan)
        self._results = results or {}
        self.asked: list[str] = []

    def plan(self) -> Sequence[SourceQuery]:
        return self._plan

    async def fetch(self, query: SourceQuery) -> SourceResult:
        self.asked.append(query.key)
        return self._results.get(query.key, SourceResult(query, (), 1))


def query(name: str) -> SourceQuery:
    return SourceQuery(FAKE, name)


def yielding(name: str, found: Sequence[Bounty]) -> SourceResult:
    return SourceResult(query(name), tuple(found), 1)


def failing(name: str, error: str) -> SourceResult:
    return SourceResult(query(name), (), 1, error=error)


def source(*named: tuple[str, SourceResult]) -> FakeSource:
    return FakeSource([query(name) for name, _ in named], dict(named))


def stored(conn: sqlite3.Connection) -> list[str]:
    page = list_bounties(
        conn, as_of=NOW, filters=BountyFilter(include_suspect=True), limit=100
    )
    return sorted(row.bounty.key for row in page.rows)


async def sweep(
    database: Database,
    gh: GitHubClient,
    sources: Sequence[FakeSource],
    *,
    planner: Planner | None = None,
    workers: int = 4,
    resume: bool = True,
    on_progress: ProgressHook | None = None,
) -> ScanOutcome:
    return await run_scan(
        database,
        gh,
        sources,
        weights=WEIGHTS,
        now=NOW,
        planner=planner,
        workers=workers,
        resume=resume,
        on_progress=on_progress,
    )


async def test_a_sweep_writes_and_scores_what_it_finds(
    database: Database, gh: GitHubClient
) -> None:
    found = source(
        ("one", yielding("one", [bounty(1)])), ("two", yielding("two", [bounty(2)]))
    )

    outcome = await sweep(database, gh, [found])

    assert stored(database.conn) == ["owner/repo#1", "owner/repo#2"]
    assert (outcome.completed, outcome.inserted, outcome.failed) == (2, 2, 0)
    # Scored on the way in, not on the way out.
    assert list_bounties(database.conn, as_of=NOW, limit=10).rows[0].score.total > 0


async def test_repository_facts_are_attached(
    database: Database, gh: GitHubClient
) -> None:
    bare = bounty(1, stars=None, language=None)

    await sweep(database, gh, [source(("one", yielding("one", [bare])))])

    row = list_bounties(database.conn, as_of=NOW, limit=1).rows[0]
    assert (row.bounty.language, row.bounty.stars) == ("TypeScript", 500)


async def test_a_repository_is_looked_up_once_however_often_it_appears(
    database: Database, gh: GitHubClient
) -> None:
    found = source(
        ("one", yielding("one", [bounty(1, stars=None)])),
        ("two", yielding("two", [bounty(2, stars=None)])),
    )

    outcome = await sweep(database, gh, [found], workers=1)

    # Two queries, one repository between them, so one lookup on top.
    assert outcome.requests == 3


async def test_the_same_issue_from_two_queries_is_one_row(
    database: Database, gh: GitHubClient
) -> None:
    found = source(
        ("one", yielding("one", [bounty(1)])), ("two", yielding("two", [bounty(1)]))
    )

    outcome = await sweep(database, gh, [found])

    assert stored(database.conn) == ["owner/repo#1"]
    assert outcome.inserted == 1


async def test_a_failed_query_is_recorded_and_the_rest_go_on(
    database: Database, gh: GitHubClient
) -> None:
    found = source(
        ("bad", failing("bad", "422 invalid query")),
        ("good", yielding("good", [bounty(1)])),
    )

    outcome = await sweep(database, gh, [found])

    assert outcome.failed == 1
    assert stored(database.conn) == ["owner/repo#1"]
    row = database.conn.execute(
        "SELECT status, error FROM scan_query WHERE query = 'bad'"
    ).fetchone()
    assert (row["status"], row["error"]) == ("failed", "422 invalid query")


async def test_per_query_yield_is_recorded(
    database: Database, gh: GitHubClient
) -> None:
    found = source(("one", yielding("one", [bounty(1), bounty(2)])))

    await sweep(database, gh, [found])

    row = database.conn.execute("SELECT * FROM scan_query").fetchone()
    assert (row["results"], row["new_bounties"]) == (2, 2)


async def test_a_second_sweep_finds_the_same_bounty_but_nothing_new(
    database: Database, gh: GitHubClient
) -> None:
    await sweep(database, gh, [source(("one", yielding("one", [bounty(1)])))])

    outcome = await sweep(
        database, gh, [source(("one", yielding("one", [bounty(1)])))], resume=False
    )

    assert (outcome.found, outcome.inserted) == (1, 0)


async def test_progress_is_reported_per_query(
    database: Database, gh: GitHubClient
) -> None:
    seen: list[ScanProgress] = []

    await sweep(
        database,
        gh,
        [source(("one", yielding("one", [bounty(1)])))],
        on_progress=seen.append,
    )

    assert len(seen) == 1
    assert (seen[0].query, seen[0].new_bounties, seen[0].planned) == ("one", 1, 1)


async def test_a_finished_run_is_recorded(database: Database, gh: GitHubClient) -> None:
    await sweep(database, gh, [FakeSource([query("one")])])

    run = scans.latest_run(database.conn)
    assert run is not None
    assert run.status is scans.RunStatus.DONE
    assert run.finished_at == NOW


# -- resumption ------------------------------------------------------------


def leave_unfinished(database: Database, done: str, error: str | None = None) -> int:
    """A run that stopped part way, with one query already recorded."""
    run_id = scans.start_run(database.conn, NOW - timedelta(hours=1), 2)
    query_id = scans.start_query(database.conn, run_id, FAKE, done, NOW)
    scans.finish_query(database.conn, query_id, NOW, results=1, error=error)
    return run_id


async def test_an_interrupted_sweep_continues_rather_than_restarts(
    database: Database, gh: GitHubClient
) -> None:
    run_id = leave_unfinished(database, "one")
    found = FakeSource([query("one"), query("two")])

    outcome = await sweep(database, gh, [found])

    assert found.asked == ["two"]
    assert (outcome.run_id, outcome.resumed) == (run_id, True)


async def test_a_query_that_failed_last_time_is_tried_again(
    database: Database, gh: GitHubClient
) -> None:
    leave_unfinished(database, "one", error="timed out")
    found = FakeSource([query("one")])

    await sweep(database, gh, [found])

    assert found.asked == ["one"]


async def test_resumption_can_be_refused(database: Database, gh: GitHubClient) -> None:
    run_id = leave_unfinished(database, "one")
    found = FakeSource([query("one")])

    outcome = await sweep(database, gh, [found], resume=False)

    assert found.asked == ["one"]
    assert outcome.run_id != run_id


# -- saturation ------------------------------------------------------------


async def test_a_saturated_query_is_split_and_the_pieces_run(
    database: Database, gh: GitHubClient
) -> None:
    planner = Planner(settings(vocabulary=("label:bounty",)), AS_OF)
    parent = planner.plan()[0].as_source_query()
    found = FakeSource(
        [parent],
        {parent.key: SourceResult(parent, (bounty(1),), 1, saturated=True)},
        name=parent.source,
    )

    outcome = await sweep(database, gh, [found], planner=planner)

    # One query in, four star bands out, and all of them run.
    assert (outcome.planned, outcome.completed) == (5, 5)
    run = scans.get_run(database.conn, outcome.run_id)
    assert run is not None
    assert run.planned_queries == 5


async def test_nothing_is_split_without_a_planner(
    database: Database, gh: GitHubClient
) -> None:
    saturated = SourceResult(query("one"), (bounty(1),), 1, saturated=True)

    outcome = await sweep(database, gh, [source(("one", saturated))])

    assert outcome.planned == 1
