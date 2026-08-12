"""Issue search: paging, precision, saturation, and refusal."""

from __future__ import annotations

from typing import Any

import httpx
import respx

from bounty_searcher.sources.base import SourceQuery
from bounty_searcher.sources.github.search import (
    MAX_RESULTS_PER_QUERY,
    RESULTS_PER_PAGE,
    SearchSource,
)
from tests.sources.clock import FakeClock
from tests.sources.github.test_client import API, client
from tests.sources.github.test_issues import issue

QUERY = SourceQuery(
    "github-search", "label:bounty state:open", params=(("order", "desc"),)
)


def results(items: list[dict[str, Any]], total: int | None = None) -> dict[str, Any]:
    return {"total_count": total if total is not None else len(items), "items": items}


def page_of(count: int, start: int = 1) -> list[dict[str, Any]]:
    return [issue(number=start + offset) for offset in range(count)]


async def test_a_query_returns_the_bounties_it_found() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        respx.get(f"{API}/search/issues").respond(200, json=results(page_of(2)))

        result = await SearchSource(gh, [QUERY]).fetch(QUERY)

    assert len(result.bounties) == 2
    assert result.requests == 1
    assert result.error is None
    assert result.saturated is False
    # The query that found it is recorded on the bounty.
    assert result.bounties[0].source == QUERY.key


async def test_the_query_is_sent_as_asked_for() -> None:
    clock = FakeClock()
    ascending = SourceQuery("github-search", "label:bounty", params=(("order", "asc"),))
    async with client(clock) as gh, respx.mock:
        route = respx.get(f"{API}/search/issues").respond(200, json=results([]))

        await SearchSource(gh, [ascending]).fetch(ascending)

    sent = route.calls.last.request.url.params
    assert sent["q"] == "label:bounty"
    assert sent["order"] == "asc"
    assert sent["sort"] == "created"
    # Legacy issue search is gone, so this is asked for by name.
    assert sent["advanced_search"] == "true"


async def test_paging_stops_when_the_results_run_out() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        route = respx.get(f"{API}/search/issues")
        route.side_effect = [
            httpx.Response(200, json=results(page_of(RESULTS_PER_PAGE), total=150)),
            httpx.Response(200, json=results(page_of(50, start=101), total=150)),
        ]

        result = await SearchSource(gh, [QUERY]).fetch(QUERY)

    assert route.call_count == 2
    assert len(result.bounties) == 150
    assert result.requests == 2


async def test_paging_stops_at_the_ceiling_and_says_so() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        route = respx.get(f"{API}/search/issues")
        route.side_effect = [
            httpx.Response(
                200,
                json=results(page_of(RESULTS_PER_PAGE, start=n * 100), total=40_000),
            )
            for n in range(20)
        ]

        result = await SearchSource(gh, [QUERY]).fetch(QUERY)

    # Ten pages is everything GitHub will give for one query, whatever it
    # claims the total is. The rest is recovered by splitting the query.
    assert route.call_count == MAX_RESULTS_PER_QUERY // RESULTS_PER_PAGE
    assert result.saturated is True


async def test_an_issue_with_no_money_in_it_is_not_a_bounty() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        respx.get(f"{API}/search/issues").respond(
            200,
            json=results(
                [
                    issue(number=1),
                    issue(number=2, labels=[], body="Just a plain bug report."),
                ]
            ),
        )

        result = await SearchSource(gh, [QUERY]).fetch(QUERY)

    assert [bounty.number for bounty in result.bounties] == [1]


async def test_the_same_issue_twice_is_one_bounty() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        respx.get(f"{API}/search/issues").respond(
            200, json=results([issue(number=1), issue(number=1)])
        )

        result = await SearchSource(gh, [QUERY]).fetch(QUERY)

    assert len(result.bounties) == 1


async def test_a_refused_query_comes_back_as_an_error_not_an_exception() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        respx.get(f"{API}/search/issues").respond(422, text="bad qualifier")

        result = await SearchSource(gh, [QUERY]).fetch(QUERY)

    # One dead query must not end a sweep.
    assert result.error is not None
    assert result.bounties == ()


async def test_a_failure_part_way_through_keeps_what_it_had() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        route = respx.get(f"{API}/search/issues")
        route.side_effect = [
            httpx.Response(200, json=results(page_of(RESULTS_PER_PAGE), total=500)),
            httpx.Response(422, text="gave up"),
        ]

        result = await SearchSource(gh, [QUERY]).fetch(QUERY)

    assert len(result.bounties) == RESULTS_PER_PAGE
    assert result.error is not None


async def test_the_plan_is_whatever_it_was_given() -> None:
    clock = FakeClock()
    async with client(clock) as gh:
        assert list(SearchSource(gh, [QUERY]).plan()) == [QUERY]
