"""Polling a watchlist, and looking a repository up."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import respx

from bounty_searcher.domain.models import Repository
from bounty_searcher.sources.base import SourceQuery
from bounty_searcher.sources.github.repos import (
    NAME,
    RESULTS_PER_PAGE,
    WatchlistSource,
    fetch_repo,
)
from tests.sources.clock import FakeClock
from tests.sources.github.test_client import API, client
from tests.sources.github.test_issues import issue

REPO = SourceQuery(NAME, "owner/name")


async def test_a_repository_lookup_returns_the_facts_scoring_needs() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        respx.get(f"{API}/repos/owner/name").respond(
            200,
            json={
                "language": "Rust",
                "stargazers_count": 4_200,
                "archived": False,
                "fork": True,
            },
        )

        assert await fetch_repo(gh, "owner/name") == Repository(
            "owner/name", "Rust", 4_200, archived=False, is_fork=True
        )


async def test_a_deleted_repository_is_not_a_failure() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        respx.get(f"{API}/repos/owner/gone").respond(404)

        assert await fetch_repo(gh, "owner/gone") is None


async def test_polling_a_repository_finds_its_bounties() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        respx.get(f"{API}/repos/owner/name/issues").respond(
            200,
            json=[
                issue(number=1),
                issue(number=2, labels=[], body="No money here."),
                issue(number=3, pull_request={}),
            ],
        )

        result = await WatchlistSource(gh, ["owner/name"]).fetch(REPO)

    assert [bounty.number for bounty in result.bounties] == [1]
    # Repository listings do not carry repository_url, so the name comes from
    # the query rather than the payload.
    assert result.bounties[0].repo == "owner/name"
    assert result.bounties[0].source == "github-watchlist:owner/name"


async def test_nothing_new_costs_nothing() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        route = respx.get(f"{API}/repos/owner/name/issues")
        route.side_effect = [
            httpx.Response(200, json=[issue(number=1)], headers={"ETag": 'W/"a"'}),
            httpx.Response(304, headers={"ETag": 'W/"a"'}),
        ]
        source = WatchlistSource(gh, ["owner/name"])

        await source.fetch(REPO)
        second = await source.fetch(REPO)

    assert second.bounties == ()
    assert route.calls[1].request.headers["If-None-Match"] == 'W/"a"'


async def test_only_what_has_moved_since_the_last_sweep_is_asked_for() -> None:
    clock = FakeClock()
    since = datetime(2026, 8, 1, 9, tzinfo=UTC)
    async with client(clock) as gh, respx.mock:
        route = respx.get(f"{API}/repos/owner/name/issues").respond(200, json=[])

        await WatchlistSource(gh, ["owner/name"], since=since).fetch(REPO)

    assert route.calls.last.request.url.params["since"] == "2026-08-01T09:00:00Z"


async def test_a_busy_repository_is_paged_to_a_limit() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        route = respx.get(f"{API}/repos/owner/name/issues").respond(
            200,
            json=[issue(number=n) for n in range(RESULTS_PER_PAGE)],
        )

        result = await WatchlistSource(gh, ["owner/name"]).fetch(REPO)

    assert route.call_count == 3
    assert result.requests == 3


async def test_a_repository_that_fails_does_not_end_the_sweep() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        respx.get(f"{API}/repos/owner/name/issues").respond(404)

        result = await WatchlistSource(gh, ["owner/name"]).fetch(REPO)

    assert result.error is not None
    assert result.bounties == ()


async def test_the_plan_is_one_query_per_repository() -> None:
    clock = FakeClock()
    async with client(clock) as gh:
        plan = WatchlistSource(gh, ["a/one", "b/two"]).plan()

    assert [query.query for query in plan] == ["a/one", "b/two"]
    assert all(query.source == NAME for query in plan)
