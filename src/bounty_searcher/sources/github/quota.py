"""The only thing allowed to decide when a request may proceed.

GitHub meters two budgets that behave nothing like each other: search allows
about 30 requests a minute, and the core API allows 5,000 an hour. A sweep uses
both at once, so they are counted separately and a worker blocked on one is not
blocked on the other.

Local counting is a guess. Every response carries the server's own view of the
budget, and that view is authoritative: retries, redirects and requests made by
anything else sharing the token all move it. So the buckets are seeded
optimistically and then corrected from the headers of every response.

On top of the two budgets sits one brake. Secondary rate limits are not
metered by the headers at all, they simply arrive, and the only correct
response is for every worker to stop until the penalty expires.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum

# Wake a moment after a window closes rather than exactly on it, so a clock
# that disagrees with GitHub's by a fraction does not spend the retry.
SETTLE_SECONDS = 1.0

# Documented ceilings for an authenticated token.
SEARCH_LIMIT = 30
SEARCH_WINDOW = 60.0
CORE_LIMIT = 5_000
CORE_WINDOW = 3_600.0

type Clock = Callable[[], float]
type Sleep = Callable[[float], Awaitable[None]]


class Budget(StrEnum):
    SEARCH = "search"
    CORE = "core"


@dataclass(frozen=True, slots=True)
class BucketState:
    """A budget as it stands, for the status line."""

    budget: Budget
    limit: int
    remaining: int
    reset_at: float


@dataclass(frozen=True, slots=True)
class QuotaSnapshot:
    search: BucketState
    core: BucketState
    paused_until: float | None


def budget_for(path: str) -> Budget:
    """Which budget a request against this path spends."""
    return Budget.SEARCH if "/search/" in path else Budget.CORE


def _as_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _as_float(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


class Bucket:
    """One budget, and the queue of workers waiting on it.

    The lock is held across the sleep on purpose. When a budget is spent
    nobody may proceed, so the worker that discovers it waits with the door
    shut rather than letting the rest through to discover the same thing.
    """

    def __init__(
        self,
        budget: Budget,
        limit: int,
        window: float,
        *,
        clock: Clock = time.time,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.budget = budget
        self.limit = limit
        self.window = window
        self._remaining = limit
        self._reset_at = clock() + window
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()

    async def take(self) -> None:
        """Wait until this budget can afford one request, then spend it."""
        async with self._lock:
            while True:
                now = self._clock()
                if now >= self._reset_at:
                    self._remaining = self.limit
                    self._reset_at = now + self.window
                if self._remaining > 0:
                    self._remaining -= 1
                    return
                await self._sleep(max(0.0, self._reset_at - now) + SETTLE_SECONDS)

    def sync(self, headers: Mapping[str, str]) -> None:
        """Adopt the server's count. It is the one that decides."""
        lowered = {name.lower(): value for name, value in headers.items()}
        remaining = _as_int(lowered.get("x-ratelimit-remaining"))
        reset_at = _as_float(lowered.get("x-ratelimit-reset"))
        if remaining is None or reset_at is None:
            return
        if (limit := _as_int(lowered.get("x-ratelimit-limit"))) is not None:
            self.limit = limit
        self._remaining = remaining
        self._reset_at = reset_at

    def state(self) -> BucketState:
        return BucketState(self.budget, self.limit, self._remaining, self._reset_at)


class Governor:
    """Both budgets and the shared brake."""

    def __init__(
        self,
        *,
        search_limit: int = SEARCH_LIMIT,
        search_window: float = SEARCH_WINDOW,
        core_limit: int = CORE_LIMIT,
        core_window: float = CORE_WINDOW,
        clock: Clock = time.time,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._buckets = {
            Budget.SEARCH: Bucket(
                Budget.SEARCH, search_limit, search_window, clock=clock, sleep=sleep
            ),
            Budget.CORE: Bucket(
                Budget.CORE, core_limit, core_window, clock=clock, sleep=sleep
            ),
        }
        self._paused_until: float | None = None

    def now(self) -> float:
        """The clock everything here measures against, epoch seconds."""
        return self._clock()

    def bucket(self, path: str) -> Bucket:
        return self._buckets[budget_for(path)]

    async def acquire(self, path: str) -> None:
        """Block until a request against this path is allowed to go out."""
        await self._wait_out_penalty()
        await self.bucket(path).take()

    def sync(self, path: str, headers: Mapping[str, str]) -> None:
        self.bucket(path).sync(headers)

    def penalise(self, seconds: float) -> None:
        """Stop every worker for a while. Extends an existing penalty."""
        until = self._clock() + seconds
        if self._paused_until is None or until > self._paused_until:
            self._paused_until = until

    async def _wait_out_penalty(self) -> None:
        while self._paused_until is not None:
            remaining = self._paused_until - self._clock()
            if remaining <= 0:
                self._paused_until = None
                return
            await self._sleep(remaining)

    def snapshot(self) -> QuotaSnapshot:
        return QuotaSnapshot(
            search=self._buckets[Budget.SEARCH].state(),
            core=self._buckets[Budget.CORE].state(),
            paused_until=self._paused_until,
        )
