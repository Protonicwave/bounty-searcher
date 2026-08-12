"""Deciding, and taking it back."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx

from bounty_searcher.store import triage
from tests.api.conftest import Harness
from tests.store.corpus import NOW, bounty, fill


def status_of(api: Harness, bounty_id: int) -> str:
    return triage.get(api.conn, bounty_id).status.value


async def apply(api: Harness, **body: Any) -> httpx.Response:
    return await api.client.post("/api/triage", json=body)


async def undo(api: Harness, **body: Any) -> list[int]:
    response = await api.client.post("/api/triage/undo", json=body)
    assert response.status_code == 200, response.text
    ids: list[int] = response.json()["bounty_ids"]
    return ids


async def test_a_transition_returns_the_token_that_undoes_it(api: Harness) -> None:
    ids = fill(api.conn, [bounty(1)])

    response = await apply(api, bounty_ids=list(ids), status="shortlisted")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "shortlisted"
    assert payload["bounty_ids"] == list(ids)
    assert payload["undo_token"]
    assert status_of(api, ids[0]) == "shortlisted"


async def test_a_run_of_rows_comes_back_under_one_token(api: Harness) -> None:
    """Holding the dismiss key is one gesture, so it is one undo."""
    ids = fill(api.conn, [bounty(1), bounty(2), bounty(3)])

    started = await apply(api, bounty_ids=list(ids), status="dismissed")
    restored = await undo(api, undo_token=started.json()["undo_token"])

    assert sorted(restored) == sorted(ids)
    assert all(status_of(api, bounty_id) == "new" for bounty_id in ids)


async def test_undo_with_no_token_reverses_the_last_transition(api: Harness) -> None:
    ids = fill(api.conn, [bounty(1), bounty(2)])
    await apply(api, bounty_ids=[ids[0]], status="shortlisted")
    await apply(api, bounty_ids=[ids[1]], status="dismissed")

    assert await undo(api) == [ids[1]]
    assert status_of(api, ids[1]) == "new"
    assert status_of(api, ids[0]) == "shortlisted"


async def test_undoing_twice_restores_nothing_the_second_time(api: Harness) -> None:
    """A keystroke repeated on a slow connection must not double-apply."""
    ids = fill(api.conn, [bounty(1)])
    started = await apply(api, bounty_ids=list(ids), status="dismissed")
    token = started.json()["undo_token"]

    assert await undo(api, undo_token=token) == [ids[0]]
    assert await undo(api, undo_token=token) == []


async def test_a_snooze_carries_its_expiry(api: Harness) -> None:
    ids = fill(api.conn, [bounty(1)])
    until = NOW + timedelta(days=7)

    response = await apply(
        api, bounty_ids=list(ids), status="snoozed", snooze_until=until.isoformat()
    )
    assert response.status_code == 200, response.text
    assert triage.get(api.conn, ids[0]).snooze_until == until


async def test_a_snooze_without_an_expiry_is_refused(api: Harness) -> None:
    """It would be a dismissal pretending to come back."""
    ids = fill(api.conn, [bounty(1)])

    response = await apply(api, bounty_ids=list(ids), status="snoozed")
    assert response.status_code == 422


async def test_an_expiry_on_anything_else_is_refused(api: Harness) -> None:
    ids = fill(api.conn, [bounty(1)])

    response = await apply(
        api,
        bounty_ids=list(ids),
        status="dismissed",
        snooze_until=NOW.isoformat(),
    )
    assert response.status_code == 422


async def test_a_stale_id_is_a_404_and_writes_nothing(api: Harness) -> None:
    ids = fill(api.conn, [bounty(1)])

    response = await apply(api, bounty_ids=[ids[0], 9999], status="dismissed")
    assert response.status_code == 404
    assert "9999" in response.json()["detail"]
    assert status_of(api, ids[0]) == "new"


async def test_an_empty_transition_is_refused(api: Harness) -> None:
    response = await apply(api, bounty_ids=[], status="dismissed")
    assert response.status_code == 422


async def test_an_unknown_status_is_refused(api: Harness) -> None:
    ids = fill(api.conn, [bounty(1)])

    response = await apply(api, bounty_ids=list(ids), status="maybe")
    assert response.status_code == 422
