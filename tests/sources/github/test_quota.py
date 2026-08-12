"""The governor: two budgets, one brake."""

from __future__ import annotations

import pytest

from bounty_searcher.sources.github.quota import Budget, Governor, budget_for
from tests.sources.clock import FakeClock


def governor(clock: FakeClock) -> Governor:
    """Small budgets, so exhausting one takes three requests rather than thirty."""
    return Governor(
        search_limit=3,
        search_window=60.0,
        core_limit=5,
        core_window=3600.0,
        clock=clock,
        sleep=clock.sleep,
    )


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/search/issues", Budget.SEARCH),
        ("/repos/owner/name", Budget.CORE),
        ("/repos/owner/name/issues/1/comments", Budget.CORE),
    ],
)
def test_path_picks_a_budget(path: str, expected: Budget) -> None:
    assert budget_for(path) is expected


async def test_spending_a_budget_waits_for_the_window_to_close() -> None:
    clock = FakeClock()
    gov = governor(clock)

    for _ in range(3):
        await gov.acquire("/search/issues")
    assert clock.slept == []

    await gov.acquire("/search/issues")

    # The fourth request waits out the rest of the window rather than being
    # refused, and the two budgets are counted apart.
    assert clock.total_slept == pytest.approx(61.0)
    assert gov.snapshot().core.remaining == 5


async def test_the_budgets_do_not_block_each_other() -> None:
    clock = FakeClock()
    gov = governor(clock)

    for _ in range(3):
        await gov.acquire("/search/issues")
    await gov.acquire("/repos/owner/name")

    assert clock.slept == []


async def test_headers_overrule_local_counting() -> None:
    clock = FakeClock()
    gov = governor(clock)

    await gov.acquire("/search/issues")
    gov.sync(
        "/search/issues",
        {
            "X-RateLimit-Limit": "30",
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(clock.now + 10),
        },
    )

    state = gov.snapshot().search
    assert (state.limit, state.remaining) == (30, 0)

    # Locally there were two left. The server says none, so the next request
    # waits, and it waits only as long as the server said.
    await gov.acquire("/search/issues")
    assert clock.total_slept == pytest.approx(11.0)


async def test_unreadable_headers_are_ignored() -> None:
    clock = FakeClock()
    gov = governor(clock)

    gov.sync(
        "/search/issues", {"X-RateLimit-Remaining": "soon", "X-RateLimit-Reset": ""}
    )

    assert gov.snapshot().search.remaining == 3


async def test_a_penalty_stops_every_budget() -> None:
    clock = FakeClock()
    gov = governor(clock)

    gov.penalise(30.0)
    await gov.acquire("/repos/owner/name")

    assert clock.total_slept == pytest.approx(30.0)
    assert gov.snapshot().paused_until is None


async def test_a_longer_penalty_extends_a_shorter_one() -> None:
    clock = FakeClock()
    gov = governor(clock)

    gov.penalise(10.0)
    gov.penalise(45.0)
    gov.penalise(5.0)
    await gov.acquire("/search/issues")

    assert clock.total_slept == pytest.approx(45.0)
