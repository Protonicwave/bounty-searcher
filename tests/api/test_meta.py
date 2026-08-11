"""The status line's one request, and the health check."""

from __future__ import annotations

from typing import Any

from bounty_searcher import __version__
from bounty_searcher.domain.models import TriageStatus
from bounty_searcher.store import scans, triage
from tests.api.conftest import Harness
from tests.store.corpus import NOW, bounty, fill


async def read(api: Harness) -> dict[str, Any]:
    response = await api.client.get("/api/meta")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_health_reads_nothing(api: Harness) -> None:
    response = await api.client.get("/api/health")
    assert response.json() == {"status": "ok", "version": __version__}


async def test_an_empty_corpus_says_so_rather_than_failing(api: Harness) -> None:
    payload = await read(api)

    assert payload["counts"] == {
        "total": 0,
        "priced": 0,
        "suspect": 0,
        "by_status": {},
    }
    assert payload["last_scan"] is None
    assert payload["quota"] is None


async def test_the_counts_describe_the_corpus(api: Harness) -> None:
    ids = fill(api.conn, [bounty(1), bounty(2, amount=None), bounty(3, stars=0)])
    triage.set_status(api.conn, [ids[0]], TriageStatus.SHORTLISTED, NOW)

    counts = (await read(api))["counts"]
    assert (counts["total"], counts["priced"], counts["suspect"]) == (3, 2, 1)
    assert counts["by_status"] == {"shortlisted": 1, "new": 2}


async def test_the_views_are_named_by_the_server(api: Harness) -> None:
    """So the interface does not keep its own copy of the labels."""
    views = (await read(api))["views"]

    assert [view["name"] for view in views] == ["tonight", "payday", "changed", "all"]
    assert all(view["title"] and view["description"] for view in views)


async def test_the_last_scan_is_summed_from_its_queries(api: Harness) -> None:
    run = scans.start_run(api.conn, NOW, planned_queries=3)
    first = scans.start_query(api.conn, run, "github", "label:bounty", NOW)
    scans.finish_query(api.conn, first, NOW, results=10, new_bounties=4)
    second = scans.start_query(api.conn, run, "github", "reward in:title", NOW)
    scans.finish_query(api.conn, second, NOW, error="rate limited")
    scans.finish_run(api.conn, run, NOW, scans.RunStatus.DONE)

    last = (await read(api))["last_scan"]
    assert last["run_id"] == run
    assert last["status"] == "done"
    assert (last["planned"], last["completed"], last["failed"]) == (3, 2, 1)
    assert last["new_bounties"] == 4
    assert last["running"] is False
