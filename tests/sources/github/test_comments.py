"""The bounties issue search cannot see."""

from __future__ import annotations

from typing import Any

import httpx
import respx

from bounty_searcher.domain.models import Confidence
from bounty_searcher.sources.base import SourceQuery
from bounty_searcher.sources.github.comments import (
    MAX_CANDIDATES,
    NAME,
    CommentSource,
    comment_amount,
)
from tests.sources.clock import FakeClock
from tests.sources.github.test_client import API, client
from tests.sources.github.test_issues import issue

REPO = SourceQuery(NAME, "owner/name", cost=2)


def comment(body: str, *, login: str = "someone", number: int = 7) -> dict[str, Any]:
    return {
        "body": body,
        "user": {"login": login},
        "issue_url": f"https://api.github.com/repos/owner/name/issues/{number}",
    }


def test_a_bot_comment_carries_a_trustworthy_figure() -> None:
    amount = comment_amount(comment("💎 $500 bounty", login="algora-pbc[bot]"))

    assert amount is not None
    assert amount.minor_units == 50_000
    # The platform has escrowed the money, so this is as good as a label.
    assert amount.confidence is Confidence.HIGH


def test_a_bounty_command_from_a_maintainer_counts() -> None:
    amount = comment_amount(comment("/bounty 250"))

    assert amount is not None
    assert amount.minor_units == 25_000


def test_somebody_mentioning_money_does_not() -> None:
    assert comment_amount(comment("I'd happily chip in $50 for this")) is None


def test_a_marker_with_no_figure_is_not_a_bounty() -> None:
    assert comment_amount(comment("see algora.io/bounties for how this works")) is None


async def test_a_commented_bounty_becomes_a_bounty() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        respx.get(f"{API}/repos/owner/name/issues/comments").respond(
            200, json=[comment("/bounty 300", number=7)]
        )
        respx.get(f"{API}/repos/owner/name/issues/7").respond(
            200,
            json=issue(number=7, labels=[], body="Nothing about money in here."),
        )

        result = await CommentSource(gh, ["owner/name"]).fetch(REPO)

    assert len(result.bounties) == 1
    found = result.bounties[0]
    # The issue itself says nothing, which is exactly why search misses it.
    assert found.amount is not None
    assert found.amount.minor_units == 30_000
    assert found.repo == "owner/name"


async def test_the_largest_figure_in_a_thread_is_the_one_that_pays() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        respx.get(f"{API}/repos/owner/name/issues/comments").respond(
            200,
            json=[
                comment("/bounty 100", number=7),
                comment("/bounty 400", number=7),
            ],
        )
        respx.get(f"{API}/repos/owner/name/issues/7").respond(200, json=issue(number=7))

        result = await CommentSource(gh, ["owner/name"]).fetch(REPO)

    assert result.bounties[0].amount is not None
    assert result.bounties[0].amount.minor_units == 40_000


async def test_a_closed_issue_is_not_an_opportunity() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        respx.get(f"{API}/repos/owner/name/issues/comments").respond(
            200, json=[comment("/bounty 300", number=7)]
        )
        respx.get(f"{API}/repos/owner/name/issues/7").respond(
            200, json=issue(number=7, state="closed")
        )

        result = await CommentSource(gh, ["owner/name"]).fetch(REPO)

    assert result.bounties == ()


async def test_resolving_candidates_is_capped() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        respx.get(f"{API}/repos/owner/name/issues/comments").respond(
            200,
            json=[comment("/bounty 100", number=n) for n in range(MAX_CANDIDATES + 5)],
        )
        issues = respx.get(url__regex=rf"{API}/repos/owner/name/issues/\d+$").respond(
            200, json=issue()
        )

        await CommentSource(gh, ["owner/name"]).fetch(REPO)

    assert issues.call_count == MAX_CANDIDATES


async def test_nothing_new_since_the_last_sweep_is_free() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        route = respx.get(f"{API}/repos/owner/name/issues/comments")
        route.side_effect = [
            httpx.Response(200, json=[], headers={"ETag": 'W/"a"'}),
            httpx.Response(304, headers={"ETag": 'W/"a"'}),
        ]
        source = CommentSource(gh, ["owner/name"])

        await source.fetch(REPO)
        second = await source.fetch(REPO)

    assert second.bounties == ()
    assert route.calls[1].request.headers["If-None-Match"] == 'W/"a"'


async def test_a_repository_that_fails_does_not_end_the_sweep() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        respx.get(f"{API}/repos/owner/name/issues/comments").respond(404)

        result = await CommentSource(gh, ["owner/name"]).fetch(REPO)

    assert result.error is not None
    assert result.bounties == ()
