"""The supervisor: one sweep at a time, and everyone watching gets told.

Run directly on the loop rather than through a client, so a subscriber can be
attached halfway through a sweep and the live broadcast is what is under test.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest

from bounty_searcher.api.scan import ScanBusy, ScanSupervisor
from bounty_searcher.config import ScanSettings
from bounty_searcher.scan.runner import (
    ProgressHook,
    ScanOutcome,
    ScanProgress,
    StartHook,
)
from bounty_searcher.store.db import Database
from tests.store.corpus import NOW, WEIGHTS

RUN_ID = 7


def progress(completed: int, planned: int = 3) -> ScanProgress:
    return ScanProgress(
        run_id=RUN_ID,
        completed=completed,
        planned=planned,
        source="github",
        query=f"label:bounty {completed}",
        results=5,
        new_bounties=2,
        requests=1,
    )


def outcome(completed: int = 3) -> ScanOutcome:
    return ScanOutcome(
        run_id=RUN_ID,
        planned=completed,
        completed=completed,
        failed=0,
        found=5 * completed,
        inserted=2 * completed,
        changed=0,
        requests=completed,
    )


class Controllable:
    """A sweep the test drives one query at a time."""

    def __init__(self) -> None:
        self.step = asyncio.Event()
        self.reported: list[int] = []
        self.calls = 0

    async def __call__(
        self, now: datetime, on_start: StartHook, on_progress: ProgressHook
    ) -> ScanOutcome:
        self.calls += 1
        on_start(RUN_ID, False)
        for completed in (1, 2, 3):
            await self.step.wait()
            self.step.clear()
            on_progress(progress(completed))
            self.reported.append(completed)
        return outcome()

    async def advance(self) -> None:
        """Let the sweep finish one query, and wait until it has."""
        expected = len(self.reported) + 1
        self.step.set()
        while len(self.reported) < expected:
            await asyncio.sleep(0)


@pytest.fixture
def sweep() -> Controllable:
    return Controllable()


@pytest.fixture
def supervisor(tmp_path: Path, sweep: Controllable) -> Iterator[ScanSupervisor]:
    with Database(tmp_path / "state.db") as db:
        yield ScanSupervisor(db, settings=ScanSettings(), weights=WEIGHTS, sweep=sweep)


async def test_start_returns_before_the_first_query(
    supervisor: ScanSupervisor, sweep: Controllable
) -> None:
    run_id, resumed = await supervisor.start(NOW)

    assert (run_id, resumed) == (RUN_ID, False)
    assert supervisor.running
    assert sweep.reported == []

    await supervisor.stop()


async def test_a_second_sweep_is_refused(
    supervisor: ScanSupervisor, sweep: Controllable
) -> None:
    await supervisor.start(NOW)

    with pytest.raises(ScanBusy):
        await supervisor.start(NOW)
    assert sweep.calls == 1

    await supervisor.stop()


async def test_every_subscriber_sees_every_query(
    supervisor: ScanSupervisor, sweep: Controllable
) -> None:
    await supervisor.start(NOW)

    async def collect() -> list[int]:
        return [event.completed async for event in supervisor.events()]

    watchers = [asyncio.create_task(collect()) for _ in range(2)]
    await asyncio.sleep(0)  # let both subscribe before anything is published

    for _ in range(3):
        await sweep.advance()

    assert await asyncio.gather(*watchers) == [[1, 2, 3], [1, 2, 3]]


async def test_a_late_subscriber_is_told_where_the_sweep_is(
    supervisor: ScanSupervisor, sweep: Controllable
) -> None:
    await supervisor.start(NOW)
    await sweep.advance()
    await sweep.advance()

    async def collect() -> list[int]:
        return [event.completed async for event in supervisor.events()]

    watcher = asyncio.create_task(collect())
    await asyncio.sleep(0)
    await sweep.advance()

    # The state it missed, then the query it was there for.
    assert await watcher == [2, 3]


async def test_watching_nothing_ends_at_once(supervisor: ScanSupervisor) -> None:
    assert [event async for event in supervisor.events()] == []


async def test_a_sweep_that_fails_before_opening_a_run_fails_the_caller(
    tmp_path: Path,
) -> None:
    async def broken(
        now: datetime, on_start: StartHook, on_progress: ProgressHook
    ) -> ScanOutcome:
        raise RuntimeError("no token")

    supervisor = ScanSupervisor(
        Database(tmp_path / "state.db"),
        settings=ScanSettings(),
        weights=WEIGHTS,
        sweep=broken,
    )

    with pytest.raises(RuntimeError, match="no token"):
        await supervisor.start(NOW)
    assert not supervisor.running


async def test_stopping_leaves_no_subscriber_waiting(
    supervisor: ScanSupervisor,
) -> None:
    """Shutdown must not hang on a stream nobody is going to feed."""
    await supervisor.start(NOW)

    async def collect() -> list[int]:
        return [event.completed async for event in supervisor.events()]

    watcher = asyncio.create_task(collect())
    await asyncio.sleep(0)
    await supervisor.stop()

    assert await asyncio.wait_for(watcher, timeout=1) == []
    assert not supervisor.running
