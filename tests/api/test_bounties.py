"""The list and the detail, through the client."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from bounty_searcher.domain.models import TriageStatus
from bounty_searcher.store import scans, triage
from tests.api.conftest import Harness
from tests.store.corpus import NOW, bounty, fill


def keys(payload: dict[str, Any]) -> list[str]:
    return [row["key"] for row in payload["rows"]]


async def get(api: Harness, **params: Any) -> dict[str, Any]:
    response = await api.client.get("/api/bounties", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def code(api: Harness, path: str = "/api/bounties", **params: Any) -> int:
    return (await api.client.get(path, params=params)).status_code


async def test_the_list_is_ranked_and_counted(api: Harness) -> None:
    fill(api.conn, [bounty(1), bounty(2), bounty(3)])

    payload = await get(api)
    assert payload["total"] == 3
    assert keys(payload) == ["owner/repo#3", "owner/repo#2", "owner/repo#1"]
    assert payload["next_cursor"] is None
    assert payload["view"] == "all"
    assert payload["sort"] == "score"


async def test_a_row_carries_what_the_interface_draws(api: Harness) -> None:
    fill(api.conn, [bounty(1, labels=("bounty", "good first issue"))])

    row = (await get(api))["rows"][0]
    assert row["amount"]["minor_units"] == 10_000
    assert row["amount"]["currency"] == "USD"
    assert row["amount"]["provenance"]["field"] == "label"
    assert row["labels"] == ["bounty", "good first issue"]
    assert row["triage"]["status"] == "new"
    assert {part["component"] for part in row["score"]["components"]} == {
        "payout",
        "language",
        "effort",
        "freshness",
        "competition",
        "repository",
    }


async def test_a_rail_segment_can_be_drawn_to_scale(api: Harness) -> None:
    """Every component publishes the best it could have managed."""
    fill(api.conn, [bounty(1)])

    row = (await get(api))["rows"][0]
    parts = {part["component"]: part for part in row["score"]["components"]}
    assert parts["payout"]["maximum"] == 40.0
    assert parts["language"]["maximum"] == 15.0


async def test_the_body_is_only_on_the_detail(api: Harness) -> None:
    ids = fill(api.conn, [bounty(1, body="Fix the thing, we pay $100.")])

    assert "body" not in (await get(api))["rows"][0]

    response = await api.client.get(f"/api/bounties/{ids[0]}")
    assert response.status_code == 200
    assert response.json()["body"] == "Fix the thing, we pay $100."


async def test_an_unknown_bounty_is_a_404(api: Harness) -> None:
    assert await code(api, "/api/bounties/9999") == 404


# -- filters ---------------------------------------------------------------


async def test_filters_narrow_the_list(api: Harness) -> None:
    fill(
        api.conn,
        [
            bounty(1, language="Rust"),
            bounty(2, stars=20),
            bounty(3, created_at=NOW - timedelta(days=400)),
        ],
    )

    assert keys(await get(api, language="rust")) == ["owner/repo#1"]
    assert keys(await get(api, min_stars=100)) == ["owner/repo#3", "owner/repo#1"]
    assert keys(await get(api, max_age_days=30)) == ["owner/repo#2", "owner/repo#1"]
    assert keys(await get(api, min_amount_minor=25_000)) == ["owner/repo#3"]


async def test_text_search_matches_a_prefix(api: Harness) -> None:
    fill(
        api.conn,
        [bounty(1, title="Pagination cursor ignored"), bounty(2, title="Flaky test")],
    )

    assert keys(await get(api, q="pagin")) == ["owner/repo#1"]


async def test_a_status_filter_reads_what_you_decided(api: Harness) -> None:
    ids = fill(api.conn, [bounty(1), bounty(2)])
    triage.set_status(api.conn, [ids[0]], TriageStatus.SHORTLISTED, NOW)

    assert keys(await get(api, statuses="shortlisted")) == ["owner/repo#1"]
    assert keys(await get(api, statuses=["new", "shortlisted"])) == [
        "owner/repo#2",
        "owner/repo#1",
    ]


async def test_a_view_supplies_the_baseline_and_a_parameter_overrides_it(
    api: Harness,
) -> None:
    """Tonight hides claimed rows; asking for them explicitly brings them back."""
    fill(api.conn, [bounty(1), bounty(2, claim_reason="assigned to someone")])

    assert keys(await get(api, view="tonight")) == ["owner/repo#1"]
    # A claim costs the row 45 points, so it comes back at the bottom.
    assert keys(await get(api, view="tonight", include_claimed=True)) == [
        "owner/repo#1",
        "owner/repo#2",
    ]


async def test_a_view_supplies_the_sort_and_the_parameter_wins(api: Harness) -> None:
    fill(api.conn, [bounty(1, amount=None), bounty(2)])

    assert (await get(api, view="payday"))["sort"] == "payout"
    assert (await get(api, view="payday", sort="score"))["sort"] == "score"


async def test_an_unknown_view_is_rejected(api: Harness) -> None:
    assert await code(api, view="nope") == 422


# -- paging ----------------------------------------------------------------


async def test_the_cursor_walks_the_whole_list_once(api: Harness) -> None:
    fill(api.conn, [bounty(n) for n in range(1, 8)])

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(4):
        params = {"limit": 3} | ({"cursor": cursor} if cursor else {})
        payload = await get(api, **params)
        seen.extend(keys(payload))
        cursor = payload["next_cursor"]
        if cursor is None:
            break

    assert len(seen) == len(set(seen)) == 7
    assert cursor is None


async def test_a_page_stays_stable_when_rows_arrive_behind_it(api: Harness) -> None:
    """A row inserted after the first page must not shift the second."""
    fill(api.conn, [bounty(n) for n in range(1, 6)])
    first = await get(api, limit=2)

    fill(api.conn, [bounty(99, amount=None)])
    second = await get(api, limit=2, cursor=first["next_cursor"])

    assert not set(keys(first)) & set(keys(second))
    assert keys(second) == ["owner/repo#3", "owner/repo#2"]


async def test_a_malformed_cursor_is_the_callers_mistake(api: Harness) -> None:
    assert await code(api, cursor="not-a-cursor") == 422


async def test_the_page_size_is_bounded(api: Harness) -> None:
    assert await code(api, limit=0) == 422
    assert await code(api, limit=5000) == 422


# -- new and changed -------------------------------------------------------


async def test_rows_are_marked_new_or_changed_against_the_last_clean_sweep(
    api: Harness,
) -> None:
    fill(api.conn, [bounty(1, title="Before"), bounty(2)])

    second = NOW + timedelta(days=1)
    fill(api.conn, [bounty(1, title="After"), bounty(3)], second)
    run = scans.start_run(api.conn, second, planned_queries=1)
    scans.finish_run(api.conn, run, second, scans.RunStatus.DONE)

    marks = {
        row["key"]: (row["is_new"], row["is_changed"])
        for row in (await get(api))["rows"]
    }
    assert marks == {
        "owner/repo#3": (True, False),
        "owner/repo#1": (False, True),
        "owner/repo#2": (False, False),
    }


async def test_nothing_is_new_before_a_sweep_has_finished(api: Harness) -> None:
    fill(api.conn, [bounty(1)])

    row = (await get(api))["rows"][0]
    assert row["is_new"] is False and row["is_changed"] is False
