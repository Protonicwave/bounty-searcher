"""The wire format, kept separate from the domain on purpose.

These models exist so the shape the interface reads can change without anyone
touching the core, and so the reverse is also true. Money crosses the wire as
minor units and timestamps as ISO 8601, and neither is ever formatted here:
that happens in exactly one place, and it is not this one.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..domain.models import (
    AmountField,
    Confidence,
    ScoreBreakdown,
    ScoreComponent,
    ScoredBounty,
    TriageStatus,
)
from ..sources.github.quota import BucketState, Budget, QuotaSnapshot
from ..store.bounties import CorpusCounts, SortKey
from ..store.scans import RunStatus, RunTotals, ScanRun
from ..store.views import View, ViewName


def _from_epoch(seconds: float) -> datetime:
    """The governor counts in epoch seconds. The wire carries ISO 8601."""
    return datetime.fromtimestamp(seconds, UTC)


class Model(BaseModel):
    """Base for every response body. Extra fields are a mistake, not a feature."""

    model_config = ConfigDict(extra="forbid", frozen=True)


# -- bounties --------------------------------------------------------------


class ProvenanceOut(Model):
    """Where the figure was read from, and the offsets to highlight."""

    field: AmountField
    pattern: str
    start: int
    end: int
    text: str


class AmountOut(Model):
    minor_units: int
    currency: str
    confidence: Confidence
    provenance: ProvenanceOut


class ComponentOut(Model):
    component: ScoreComponent
    value: float
    # What this component could have reached under the current weights, so a
    # rail segment can be drawn to scale.
    maximum: float


class ScoreOut(Model):
    total: float
    base: float
    components: list[ComponentOut]
    weights_hash: str


class TriageOut(Model):
    """The decision as it now stands. An expired snooze reads as new again."""

    status: TriageStatus
    snooze_until: datetime | None
    updated_at: datetime | None


class BountyRow(Model):
    """One row of the list. No body: it is the largest field and unread here."""

    id: int
    key: str
    source: str
    repo: str
    number: int
    title: str
    url: str
    state: str
    labels: list[str]
    comments: int
    assignee: str | None
    language: str | None
    stars: int | None
    is_fork: bool
    claim_reason: str | None
    suspect_reason: str | None
    amount: AmountOut | None
    created_at: datetime
    updated_at: datetime
    first_seen_at: datetime | None
    changed_at: datetime | None
    # Since the last scan that finished cleanly. New wins over changed, since a
    # bounty that has just arrived has not changed, it has appeared.
    is_new: bool
    is_changed: bool
    score: ScoreOut
    triage: TriageOut


class BountyDetail(BountyRow):
    body: str


class BountyPage(Model):
    rows: list[BountyRow]
    # How many matched, not how many are on this page.
    total: int
    next_cursor: str | None
    # The view and sort actually applied, after any explicit parameter.
    view: ViewName
    sort: SortKey


# -- triage ----------------------------------------------------------------


class TriageRequest(Model):
    """Move one or several bounties to a status under a single undo."""

    bounty_ids: list[int] = Field(min_length=1)
    status: TriageStatus
    snooze_until: datetime | None = None

    @model_validator(mode="after")
    def _snooze_needs_an_expiry(self) -> Self:
        if self.status is TriageStatus.SNOOZED and self.snooze_until is None:
            # A snooze with no expiry is a dismissal that pretends otherwise.
            raise ValueError("snoozed requires snooze_until")
        if self.status is not TriageStatus.SNOOZED and self.snooze_until is not None:
            raise ValueError("snooze_until only applies to snoozed")
        return self


class TriageResult(Model):
    bounty_ids: list[int]
    status: TriageStatus
    # Hand this back to undo the whole transition, however many rows it covered.
    undo_token: str


class UndoRequest(Model):
    """Which transition to reverse. Omit the token to reverse the last one."""

    undo_token: str | None = None


class UndoResult(Model):
    bounty_ids: list[int]


# -- scans -----------------------------------------------------------------


class ScanStarted(Model):
    run_id: int
    # True when an unfinished sweep was picked up rather than a new one begun.
    resumed: bool


class ScanEvent(Model):
    """One query finished. What the progress line is drawn from."""

    run_id: int
    completed: int
    planned: int
    source: str
    query: str
    results: int
    new_bounties: int
    error: str | None


# -- metadata --------------------------------------------------------------


class BucketOut(Model):
    budget: Budget
    limit: int
    remaining: int
    reset_at: datetime


class QuotaOut(Model):
    search: BucketOut
    core: BucketOut
    # Set while a secondary rate limit is being waited out, when no request of
    # any kind may go out.
    paused_until: datetime | None


class CountsOut(Model):
    total: int
    priced: int
    suspect: int
    by_status: dict[TriageStatus, int]


class ScanOut(Model):
    run_id: int
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None
    planned: int
    completed: int
    failed: int
    new_bounties: int
    error: str | None
    running: bool


class ViewOut(Model):
    name: ViewName
    title: str
    description: str


class MetaOut(Model):
    """Everything the status line needs, in one request."""

    version: str
    counts: CountsOut
    views: list[ViewOut]
    last_scan: ScanOut | None
    # None until a sweep has run in this process. There is no honest way to know
    # the remaining budget without having asked GitHub.
    quota: QuotaOut | None


class HealthOut(Model):
    status: str
    version: str


# -- building them ---------------------------------------------------------


def score_out(
    breakdown: ScoreBreakdown, maxima: Mapping[ScoreComponent, float]
) -> ScoreOut:
    """The breakdown, with the maxima the current weights imply.

    Maxima are a property of the weights rather than of the row, so they are not
    stored per bounty and are filled in on the way out.
    """
    return ScoreOut(
        total=breakdown.total,
        base=breakdown.base,
        components=[
            ComponentOut(
                component=part.component,
                value=part.value,
                maximum=maxima.get(part.component, 0.0),
            )
            for part in breakdown.components
        ],
        weights_hash=breakdown.weights_hash,
    )


def amount_out(scored: ScoredBounty) -> AmountOut | None:
    amount = scored.bounty.amount
    if amount is None:
        return None
    provenance = amount.provenance
    return AmountOut(
        minor_units=amount.minor_units,
        currency=amount.currency,
        confidence=amount.confidence,
        provenance=ProvenanceOut(
            field=provenance.field,
            pattern=provenance.pattern,
            start=provenance.start,
            end=provenance.end,
            text=provenance.text,
        ),
    )


def _is_new(scored: ScoredBounty, since: datetime | None) -> bool:
    if since is None or scored.first_seen_at is None:
        return False
    return scored.first_seen_at >= since


def _is_changed(scored: ScoredBounty, since: datetime | None) -> bool:
    if since is None or scored.changed_at is None or _is_new(scored, since):
        return False
    return scored.changed_at >= since


def row_out(
    scored: ScoredBounty,
    *,
    maxima: Mapping[ScoreComponent, float],
    as_of: datetime,
    since: datetime | None,
) -> BountyRow:
    """One list row. ``since`` is when the last clean sweep began."""
    b = scored.bounty
    return BountyRow(
        id=scored.bounty_id or 0,
        key=b.key,
        source=b.source,
        repo=b.repo,
        number=b.number,
        title=b.title,
        url=b.url,
        state=b.state,
        labels=list(b.labels),
        comments=b.comments,
        assignee=b.assignee,
        language=b.language,
        stars=b.stars,
        is_fork=b.is_fork,
        claim_reason=b.claim_reason,
        suspect_reason=scored.suspect_reason,
        amount=amount_out(scored),
        created_at=b.created_at,
        updated_at=b.updated_at,
        first_seen_at=scored.first_seen_at,
        changed_at=scored.changed_at,
        is_new=_is_new(scored, since),
        is_changed=_is_changed(scored, since),
        score=score_out(scored.score, maxima),
        triage=TriageOut(
            status=scored.triage.effective_status(as_of),
            snooze_until=scored.triage.snooze_until,
            updated_at=scored.triage.updated_at,
        ),
    )


def detail_out(
    scored: ScoredBounty,
    *,
    maxima: Mapping[ScoreComponent, float],
    as_of: datetime,
    since: datetime | None,
) -> BountyDetail:
    """The same row with the body, which only ever loads one at a time."""
    row = row_out(scored, maxima=maxima, as_of=as_of, since=since)
    return BountyDetail(**row.model_dump(), body=scored.bounty.body)


def view_out(view: View) -> ViewOut:
    return ViewOut(name=view.name, title=view.title, description=view.description)


def counts_out(counts: CorpusCounts) -> CountsOut:
    return CountsOut(
        total=counts.total,
        priced=counts.priced,
        suspect=counts.suspect,
        by_status=counts.by_status,
    )


def _bucket_out(state: BucketState) -> BucketOut:
    return BucketOut(
        budget=state.budget,
        limit=state.limit,
        remaining=state.remaining,
        reset_at=_from_epoch(state.reset_at),
    )


def quota_out(snapshot: QuotaSnapshot | None) -> QuotaOut | None:
    if snapshot is None:
        return None
    return QuotaOut(
        search=_bucket_out(snapshot.search),
        core=_bucket_out(snapshot.core),
        paused_until=(
            None
            if snapshot.paused_until is None
            else _from_epoch(snapshot.paused_until)
        ),
    )


def scan_out(run: ScanRun, totals: RunTotals, *, running: bool) -> ScanOut:
    return ScanOut(
        run_id=run.id,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        planned=run.planned_queries,
        completed=totals.completed,
        failed=totals.failed,
        new_bounties=totals.new_bounties,
        error=run.error,
        running=running,
    )
