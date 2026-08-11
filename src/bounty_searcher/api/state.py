"""What every route needs, and how it gets hold of it.

One database connection serves the whole process, including a scan running in
the background. That is safe because nothing here blocks: every route is a
coroutine, so it runs on the event loop rather than in a thread pool, and the
store functions contain no awaits. A handler therefore runs start to finish
between two awaits and cannot interleave with the scan's writes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request

from ..domain.scoring import ScoreWeights
from ..store.db import Database
from .scan import ScanSupervisor

type Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class AppState:
    """The process-wide handles, read once by the application factory."""

    db: Database
    weights: ScoreWeights
    scans: ScanSupervisor
    # Read once per request and passed down, so everything a request filters,
    # scores and formats agrees on what "now" is.
    clock: Clock = utc_now


def _state(request: Request) -> AppState:
    state: AppState = request.app.state.app
    return state


def _now(state: Annotated[AppState, Depends(_state)]) -> datetime:
    return state.clock()


State = Annotated[AppState, Depends(_state)]
Now = Annotated[datetime, Depends(_now)]
