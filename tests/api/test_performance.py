"""The latency budget the interface is designed around.

A page has to come back faster than a keystroke feels, over a corpus far larger
than a night's triage, because every filter change and every scroll is one of
these. Measured at the 95th percentile rather than the mean: the slow one is the
one you notice.

Two things keep the tail measuring the query rather than the machine. Each shape
is run a few times before it is timed, because the first runs pay for a plan and
for index pages nothing has touched yet. And the collector is held off, because a
tail over sixty requests is otherwise largely a record of when it last walked the
corpus this fixture left on the heap.
"""

from __future__ import annotations

import gc
import statistics
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

from bounty_searcher.api.app import create_app
from bounty_searcher.store.db import Database
from tests.conftest import CORPUS_SIZE
from tests.store.corpus import NOW, WEIGHTS

LIST_BUDGET_MS = 25.0
REQUESTS = 60
# The first few runs of a query shape pay for a plan and for index pages that
# have not been touched yet, and cost roughly a third more. The budget is about
# what triage feels like, which is the steady state after the first keystroke.
WARMUP = 5


@pytest.fixture
async def client(large_corpus: Path) -> AsyncIterator[httpx.AsyncClient]:
    with Database(large_corpus) as db:
        app = create_app(db, weights=WEIGHTS, clock=lambda: NOW)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://corpus"
        ) as opened:
            yield opened


@contextmanager
def quiet_heap() -> Iterator[None]:
    """Keep the rest of the session's heap out of the measurement."""
    gc.collect()
    gc.disable()
    try:
        yield
    finally:
        gc.enable()


async def measure(
    client: httpx.AsyncClient, **params: str | int | float
) -> list[float]:
    """Milliseconds per request, after warm-up runs that are not counted."""
    for _ in range(WARMUP):
        await client.get("/api/bounties", params=params)

    timings = []
    with quiet_heap():
        for _ in range(REQUESTS):
            started = time.perf_counter()
            response = await client.get("/api/bounties", params=params)
            timings.append((time.perf_counter() - started) * 1000)
            assert response.status_code == 200
    return timings


def p95(timings: list[float]) -> float:
    return statistics.quantiles(timings, n=20)[-1]


def within_budget(timings: list[float]) -> None:
    assert p95(timings) < LIST_BUDGET_MS, (
        f"p95 {p95(timings):.1f}ms, median {statistics.median(timings):.1f}ms,"
        f" slowest {max(timings):.1f}ms"
    )


async def test_the_corpus_is_the_size_the_budget_assumes(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/api/bounties", params={"limit": 1})
    assert response.json()["total"] == CORPUS_SIZE


async def test_a_ranked_page_is_faster_than_a_keystroke(
    client: httpx.AsyncClient,
) -> None:
    timings = await measure(client, view="all", limit=50)

    within_budget(timings)


async def test_a_filtered_page_is_no_slower(client: httpx.AsyncClient) -> None:
    """The filters go to SQLite, so adding them must not change the shape."""
    timings = await measure(
        client,
        view="tonight",
        language="rust",
        min_stars=100,
        max_age_days=90,
        limit=50,
    )

    within_budget(timings)


async def test_text_search_is_no_slower(client: httpx.AsyncClient) -> None:
    """The tightest of these: the count and the page each consult the index."""
    timings = await measure(client, q="pagination cur", limit=50)

    within_budget(timings)


async def test_paging_deep_stays_inside_the_budget(client: httpx.AsyncClient) -> None:
    """A keyset cursor does not get slower the further in it goes."""
    for _ in range(WARMUP):
        await client.get("/api/bounties", params={"limit": 50})

    cursor: str | None = None
    timings = []
    with quiet_heap():
        for _ in range(20):
            params: dict[str, str | int] = {"limit": 50}
            if cursor:
                params["cursor"] = cursor
            started = time.perf_counter()
            response = await client.get("/api/bounties", params=params)
            timings.append((time.perf_counter() - started) * 1000)
            cursor = response.json()["next_cursor"]
            assert cursor is not None

    within_budget(timings)


async def test_one_bounty_comes_back_at_once(client: httpx.AsyncClient) -> None:
    row = (await client.get("/api/bounties", params={"limit": 1})).json()["rows"][0]
    for _ in range(WARMUP):
        await client.get(f"/api/bounties/{row['id']}")

    timings = []
    with quiet_heap():
        for _ in range(REQUESTS):
            started = time.perf_counter()
            response = await client.get(f"/api/bounties/{row['id']}")
            timings.append((time.perf_counter() - started) * 1000)
            assert response.status_code == 200

    within_budget(timings)
