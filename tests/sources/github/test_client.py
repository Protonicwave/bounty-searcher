"""Transport behaviour: what gets retried, what gets waited out, what does not.

Every request here is served by respx. Nothing in this suite touches the
network.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from bounty_searcher.sources.github.client import (
    GitHubClient,
    InvalidQuery,
    NotFound,
    RateLimited,
)
from bounty_searcher.sources.github.quota import Governor
from tests.sources.clock import FakeClock

API = "https://api.github.com"


def client(clock: FakeClock, etags: dict[str, str] | None = None) -> GitHubClient:
    """A client whose every wait is served by the fake clock."""
    return GitHubClient(
        "token",
        governor=Governor(clock=clock, sleep=clock.sleep),
        etags=etags,
        sleep=clock.sleep,
        # No randomness: backoff is asserted on, so it has to be a number.
        jitter=lambda: 0.0,
    )


async def test_a_successful_request_returns_json_and_syncs_the_budget() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        respx.get(f"{API}/repos/owner/name").respond(
            200,
            json={"full_name": "owner/name"},
            headers={
                "X-RateLimit-Limit": "5000",
                "X-RateLimit-Remaining": "4321",
                "X-RateLimit-Reset": str(clock.now + 100),
            },
        )

        assert await gh.get_json("/repos/owner/name") == {"full_name": "owner/name"}
        assert gh.governor.snapshot().core.remaining == 4321


async def test_the_authorization_header_carries_the_token() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        route = respx.get(f"{API}/repos/owner/name").respond(200, json={})
        await gh.get_json("/repos/owner/name")

    assert route.calls.last.request.headers["Authorization"] == "Bearer token"


async def test_an_invalid_query_is_never_retried() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        route = respx.get(f"{API}/search/issues").respond(422, text="bad qualifier")

        with pytest.raises(InvalidQuery):
            await gh.get_json("/search/issues", {"q": "nonsense:"})

    # GitHub will refuse this just as firmly the second time.
    assert route.call_count == 1


async def test_a_missing_resource_is_its_own_failure() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        respx.get(f"{API}/repos/owner/gone").respond(404)

        with pytest.raises(NotFound):
            await gh.get_json("/repos/owner/gone")


async def test_a_server_error_is_retried_with_backoff() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        route = respx.get(f"{API}/repos/owner/name")
        route.side_effect = [
            httpx.Response(502),
            httpx.Response(200, json={"ok": True}),
        ]

        assert await gh.get_json("/repos/owner/name") == {"ok": True}

    assert route.call_count == 2
    assert clock.slept == [1.0]


async def test_a_dropped_connection_is_retried() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        route = respx.get(f"{API}/repos/owner/name")
        route.side_effect = [
            httpx.ConnectError("reset"),
            httpx.Response(200, json={"ok": True}),
        ]

        assert await gh.get_json("/repos/owner/name") == {"ok": True}

    assert route.call_count == 2


async def test_retry_after_is_obeyed_and_stops_every_worker() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        route = respx.get(f"{API}/search/issues")
        route.side_effect = [
            httpx.Response(403, headers={"Retry-After": "20"}),
            httpx.Response(200, json={"items": []}),
        ]

        await gh.get_json("/search/issues", {"q": "bounty"})

        # The penalty is served by the governor, so a request on the other
        # budget would have waited too.
        assert clock.total_slept == pytest.approx(20.0)


async def test_an_exhausted_budget_waits_until_it_resets() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        route = respx.get(f"{API}/search/issues")
        route.side_effect = [
            httpx.Response(
                403,
                headers={
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(clock.now + 45),
                },
            ),
            httpx.Response(200, json={"items": []}),
        ]

        await gh.get_json("/search/issues", {"q": "bounty"})

    assert clock.total_slept == pytest.approx(45.0)


async def test_a_penalty_too_long_to_wait_out_fails_the_query() -> None:
    clock = FakeClock()
    async with client(clock) as gh, respx.mock:
        respx.get(f"{API}/search/issues").respond(429, headers={"Retry-After": "3600"})

        with pytest.raises(RateLimited):
            await gh.get_json("/search/issues", {"q": "bounty"})


async def test_a_conditional_request_sends_and_stores_the_entity_tag() -> None:
    clock = FakeClock()
    etags: dict[str, str] = {}
    async with client(clock, etags=etags) as gh, respx.mock:
        route = respx.get(f"{API}/repos/owner/name/issues")
        route.side_effect = [
            httpx.Response(200, json=[{"number": 1}], headers={"ETag": 'W/"abc"'}),
            httpx.Response(304, headers={"ETag": 'W/"abc"'}),
        ]

        first = await gh.get_json("/repos/owner/name/issues", conditional=True)
        second = await gh.get_json("/repos/owner/name/issues", conditional=True)

    assert first == [{"number": 1}]
    # Nothing has changed, and a 304 costs no quota at all.
    assert second is None
    assert route.calls[1].request.headers["If-None-Match"] == 'W/"abc"'
    assert etags == {"/repos/owner/name/issues": 'W/"abc"'}


async def test_entity_tags_are_kept_per_set_of_parameters() -> None:
    clock = FakeClock()
    etags: dict[str, str] = {}
    async with client(clock, etags=etags) as gh, respx.mock:
        respx.get(f"{API}/repos/owner/name/issues").respond(
            200, json=[], headers={"ETag": 'W/"abc"'}
        )

        await gh.get_json("/repos/owner/name/issues", {"page": 1}, conditional=True)
        await gh.get_json("/repos/owner/name/issues", {"page": 2}, conditional=True)

    assert sorted(etags) == [
        "/repos/owner/name/issues?page=1",
        "/repos/owner/name/issues?page=2",
    ]
