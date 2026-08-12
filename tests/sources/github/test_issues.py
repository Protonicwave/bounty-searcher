"""Issue JSON to bounties, and the deep check for issues already taken."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import respx

from bounty_searcher.sources.github.issues import (
    find_claim,
    issue_to_bounty,
    parse_ts,
    repo_from_url,
)
from tests.domain.builders import amount
from tests.sources.clock import FakeClock
from tests.sources.github.test_client import API, client


def issue(**kwargs: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "number": 7,
        "title": "Fix the flaky retry logic",
        "html_url": "https://github.com/owner/name/issues/7",
        "repository_url": "https://api.github.com/repos/owner/name",
        "created_at": "2026-05-01T09:00:00Z",
        "updated_at": "2026-05-02T09:00:00Z",
        "labels": [{"name": "bounty"}],
        "body": "We will pay $250 for this.",
        "comments": 3,
        "state": "open",
    }
    payload.update(kwargs)
    return payload


def test_timestamps_come_back_as_aware_utc() -> None:
    assert parse_ts("2026-05-01T09:00:00Z") == datetime(2026, 5, 1, 9, tzinfo=UTC)


def test_the_repository_is_read_off_the_api_url() -> None:
    assert repo_from_url("https://api.github.com/repos/owner/name") == "owner/name"


def test_an_issue_becomes_a_bounty() -> None:
    bounty = issue_to_bounty(issue(), source="label:bounty")

    assert bounty is not None
    assert bounty.repo == "owner/name"
    assert bounty.number == 7
    assert bounty.labels == ("bounty",)
    assert bounty.comments == 3
    assert bounty.amount is not None
    assert bounty.amount.minor_units == 25_000


def test_a_pull_request_is_not_a_bounty() -> None:
    assert issue_to_bounty(issue(pull_request={}), source="q") is None


def test_an_assignee_is_a_claim() -> None:
    bounty = issue_to_bounty(issue(assignee={"login": "someone"}), source="q")

    assert bounty is not None
    assert bounty.claim_reason == "assigned to @someone"


def test_a_known_repository_is_not_looked_up_again() -> None:
    """Repository listings do not carry repository_url, and do not need to."""
    payload = issue()
    del payload["repository_url"]

    bounty = issue_to_bounty(payload, source="watchlist", repo="other/thing")

    assert bounty is not None
    assert bounty.repo == "other/thing"


def test_a_supplied_amount_beats_the_issue_text() -> None:
    bounty = issue_to_bounty(issue(), source="comments", amount=amount(900))

    assert bounty is not None
    assert bounty.amount is not None
    assert bounty.amount.minor_units == 90_000


async def test_an_open_pull_request_against_the_issue_is_a_claim() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        respx.get(f"{API}/repos/owner/name/issues/7/timeline").respond(
            200,
            json=[
                {
                    "event": "cross-referenced",
                    "source": {
                        "issue": {"number": 12, "state": "open", "pull_request": {}}
                    },
                }
            ],
        )

        assert await find_claim(gh, "owner/name", 7) == "open PR #12 references it"


async def test_calling_dibs_in_a_comment_is_a_claim() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        respx.get(f"{API}/repos/owner/name/issues/7/timeline").respond(200, json=[])
        respx.get(f"{API}/repos/owner/name/issues/7/comments").respond(
            200,
            json=[{"body": "I'll take this one", "user": {"login": "racer"}}],
        )

        assert await find_claim(gh, "owner/name", 7) == "@racer claimed it in a comment"


async def test_a_quiet_issue_is_unclaimed() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        respx.get(f"{API}/repos/owner/name/issues/7/timeline").respond(200, json=[])
        respx.get(f"{API}/repos/owner/name/issues/7/comments").respond(
            200, json=[{"body": "Any update?", "user": {"login": "watcher"}}]
        )

        assert await find_claim(gh, "owner/name", 7) is None
