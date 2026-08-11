"""A clock that only moves when something sleeps.

Quota is all about waiting, and a test that actually waits is a test nobody
runs. Sleeping here advances the clock instead, so a sixty second window costs
nothing and the wait itself is what gets asserted on.
"""

from __future__ import annotations

START = 1_700_000_000.0


class FakeClock:
    def __init__(self, start: float = START) -> None:
        self.now = start
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds

    @property
    def total_slept(self) -> float:
        return sum(self.slept)
