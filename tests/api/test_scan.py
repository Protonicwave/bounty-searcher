"""The scan routes: starting one, and the shape of the event stream.

Neither test client delivers a response body until the request has finished, so
the stream is read by leaving the request in flight, driving the sweep to its
end, and then reading what arrived. That still exercises live delivery: the
subscriber is attached before any of these queries is reported.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

import httpx

from bounty_searcher.scan.runner import (
    ProgressHook,
    ScanOutcome,
    ScanProgress,
    StartHook,
)
from tests.api.conftest import Build, Harness

RUN_ID = 7

# Long enough for a request to reach the point of subscribing, which takes
# microseconds, and short enough not to be felt.
SETTLE = 0.05


class Controllable:
    """A sweep the test drives one query at a time, then lets finish."""

    def __init__(self, queries: int = 3) -> None:
        self.queries = queries
        self.step = asyncio.Event()
        self.reported = 0
        self.calls = 0

    async def __call__(
        self, now: datetime, on_start: StartHook, on_progress: ProgressHook
    ) -> ScanOutcome:
        self.calls += 1
        on_start(RUN_ID, False)
        for completed in range(1, self.queries + 1):
            await self.step.wait()
            self.step.clear()
            on_progress(
                ScanProgress(
                    run_id=RUN_ID,
                    completed=completed,
                    planned=self.queries,
                    source="github",
                    query=f"label:bounty {completed}",
                    results=5,
                    new_bounties=2,
                    requests=1,
                )
            )
            self.reported = completed
        return ScanOutcome(
            run_id=RUN_ID,
            planned=self.queries,
            completed=self.queries,
            failed=0,
            found=5 * self.queries,
            inserted=2 * self.queries,
            changed=0,
            requests=self.queries,
        )

    async def advance(self) -> None:
        """Let the sweep report one query, and wait until it has."""
        expected = self.reported + 1
        self.step.set()
        while self.reported < expected:
            await asyncio.sleep(0)


def frames(response: httpx.Response) -> list[tuple[str, dict[str, Any]]]:
    """Parse an event stream into (event name, payload) pairs."""
    parsed = []
    for block in response.text.strip().split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if ": " in line
        )
        if "event" in fields:
            parsed.append((fields["event"], json.loads(fields["data"])))
    return parsed


async def test_starting_a_sweep_answers_with_its_run(build: Build) -> None:
    api = await build(sweep=Controllable())

    response = await api.client.post("/api/scan")
    assert response.status_code == 200, response.text
    assert response.json() == {"run_id": RUN_ID, "resumed": False}


async def test_a_second_sweep_is_a_conflict(build: Build) -> None:
    """Two at once would fight over one quota."""
    sweep = Controllable()
    api = await build(sweep=sweep)

    assert (await api.client.post("/api/scan")).status_code == 200
    assert (await api.client.post("/api/scan")).status_code == 409
    assert sweep.calls == 1


async def test_the_stream_carries_each_query_and_then_ends(build: Build) -> None:
    sweep = Controllable(queries=3)
    api = await build(sweep=sweep)
    await api.client.post("/api/scan")

    watching = asyncio.create_task(api.client.get("/api/scan/events"))
    await asyncio.sleep(SETTLE)
    for _ in range(3):
        await sweep.advance()
    response = await watching

    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-store"

    events = frames(response)
    assert events[-1] == ("done", {})
    assert [payload["completed"] for name, payload in events if name == "progress"] == [
        1,
        2,
        3,
    ]
    assert events[0][1] == {
        "run_id": RUN_ID,
        "completed": 1,
        "planned": 3,
        "source": "github",
        "query": "label:bounty 1",
        "results": 5,
        "new_bounties": 2,
        "error": None,
    }


async def test_the_stream_ends_at_once_when_nothing_is_running(api: Harness) -> None:
    response = await api.client.get("/api/scan/events")

    assert frames(response) == [("done", {})]
