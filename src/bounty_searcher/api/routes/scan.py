"""Starting a sweep, and watching it without polling for it.

The stream is server-sent events over one connection. Progress arrives when a
query finishes, which is the only moment anything the interface draws changes,
so there is nothing to poll for in between.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from ...scan.runner import ScanProgress
from ..scan import ScanBusy
from ..schemas import ScanEvent, ScanStarted
from ..state import Now, State

router = APIRouter(prefix="/scan", tags=["scan"])

# Told to the browser so it does not reconnect the moment a sweep ends.
RETRY_MS = 5_000


@router.post(
    "",
    response_model=ScanStarted,
    responses={status.HTTP_409_CONFLICT: {"description": "A scan is already running"}},
)
async def start(state: State, now: Now) -> ScanStarted:
    """Begin a sweep in the background and return its run identifier.

    Returns as soon as the run has an identity, which is before the first
    request goes out. Watch `/scan/events` for the rest.
    """
    try:
        run_id, resumed = await state.scans.start(now)
    except ScanBusy as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return ScanStarted(run_id=run_id, resumed=resumed)


def _event(progress: ScanProgress) -> ScanEvent:
    return ScanEvent(
        run_id=progress.run_id,
        completed=progress.completed,
        planned=progress.planned,
        source=progress.source,
        query=progress.query,
        results=progress.results,
        new_bounties=progress.new_bounties,
        error=progress.error,
    )


def _frame(name: str, payload: str) -> str:
    return f"event: {name}\ndata: {payload}\n\n"


@router.get(
    "/events",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Progress until the sweep stops",
            "content": {"text/event-stream": {}},
        }
    },
)
async def events(state: State) -> StreamingResponse:
    """Stream this sweep's progress until it stops.

    Ends rather than waits when no sweep is running: there is nothing coming,
    and a connection held open to say so is a connection wasted.
    """

    async def stream() -> AsyncIterator[str]:
        yield f"retry: {RETRY_MS}\n\n"
        async for progress in state.scans.events():
            yield _frame("progress", _event(progress).model_dump_json())
        yield _frame("done", "{}")

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            # Proxies that buffer would defeat the point of streaming.
            "X-Accel-Buffering": "no",
        },
    )
