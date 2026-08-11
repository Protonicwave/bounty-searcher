"""The data types everything else is written against.

All of these are frozen. A scan produces bounties, scoring produces breakdowns,
and nothing edits either in place, so a value that has been read from the
corpus can be passed around without anyone wondering who owns it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

# Every currency the parser recognises is a two-decimal currency, so one
# exponent covers all of them. Add a per-currency table only when that stops
# being true.
MINOR_UNIT_EXPONENT = 2
_MINOR_UNITS = 10**MINOR_UNIT_EXPONENT


class AmountField(StrEnum):
    """The part of an issue a payout figure was found in."""

    LABEL = "label"
    TITLE = "title"
    BODY = "body"
    COMMENT = "comment"


class Confidence(StrEnum):
    """How much the figure is to be trusted as a real, offered payout.

    A number on a maintainer-applied label is close to authoritative. The same
    number in the middle of a body is often somebody quoting a different issue.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class Provenance:
    """Exactly where a payout figure came from.

    ``start`` and ``end`` are character offsets into the field named by
    ``field``: the issue body, the title, or the individual label text. They
    survive body cleaning, so the interface can highlight the matched run of
    text in place rather than searching for it again.
    """

    field: AmountField
    pattern: str
    start: int
    end: int
    text: str


@dataclass(frozen=True, slots=True)
class Amount:
    """A payout, held in minor units so arithmetic is exact.

    Money is never a float here. A bounty of $1,000 is 100000, and comparisons
    against a threshold are integer comparisons.
    """

    minor_units: int
    currency: str
    confidence: Confidence
    provenance: Provenance

    @classmethod
    def from_units(
        cls,
        units: Decimal,
        currency: str,
        confidence: Confidence,
        provenance: Provenance,
    ) -> Amount:
        minor = (units * _MINOR_UNITS).to_integral_value(rounding=ROUND_HALF_UP)
        return cls(int(minor), currency, confidence, provenance)

    @property
    def units(self) -> Decimal:
        """The value in major units, for display and for comparisons."""
        return Decimal(self.minor_units).scaleb(-MINOR_UNIT_EXPONENT)


@dataclass(frozen=True, slots=True)
class Repository:
    """The repository facts that scoring cares about.

    Search results do not carry any of this, so it is fetched once per
    repository and cached, then copied onto every bounty found there.
    """

    name: str  # "owner/name"
    language: str | None = None
    stars: int | None = None
    archived: bool = False
    is_fork: bool = False


class TriageStatus(StrEnum):
    NEW = "new"
    SHORTLISTED = "shortlisted"
    DISMISSED = "dismissed"
    APPLIED = "applied"
    SNOOZED = "snoozed"


@dataclass(frozen=True, slots=True)
class Triage:
    """What you have decided about a bounty, if anything."""

    status: TriageStatus = TriageStatus.NEW
    snooze_until: datetime | None = None
    updated_at: datetime | None = None

    def effective_status(self, as_of: datetime) -> TriageStatus:
        """The status to filter on now.

        An expired snooze reads as new again, which is the whole point of
        snoozing: the bounty comes back rather than being quietly lost.
        """
        expired = self.snooze_until is None or self.snooze_until <= as_of
        if self.status is TriageStatus.SNOOZED and expired:
            return TriageStatus.NEW
        return self.status


class ScoreComponent(StrEnum):
    """The six contributions a score is made of.

    Fixed at six because the score rail in the interface draws one segment per
    component. Anything finer belongs inside one of these, not beside them.
    """

    PAYOUT = "payout"
    LANGUAGE = "language"
    EFFORT = "effort"
    FRESHNESS = "freshness"
    COMPETITION = "competition"
    REPOSITORY = "repository"


@dataclass(frozen=True, slots=True)
class ComponentScore:
    """One component's contribution, and the best it could have managed.

    ``maximum`` is what this component would have scored for a perfect bounty
    under the same weights. It is what lets the rail draw a segment to scale
    and the breakdown say "9 of a possible 15" rather than a bare number.
    """

    component: ScoreComponent
    value: float
    maximum: float


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:
    """A total, its parts, and the weights that produced it.

    ``weights_hash`` identifies the weight configuration used. A row whose hash
    no longer matches the current weights is stale and needs re-scoring, which
    is a local pass over stored fields and never a refetch.
    """

    total: float
    base: float
    components: tuple[ComponentScore, ...]
    weights_hash: str

    def value(self, component: ScoreComponent) -> float:
        for part in self.components:
            if part.component is component:
                return part.value
        return 0.0


@dataclass(frozen=True, slots=True)
class Bounty:
    """One GitHub issue with money attached to it."""

    source: str
    repo: str  # "owner/name"
    number: int
    title: str
    url: str
    created_at: datetime
    updated_at: datetime
    labels: tuple[str, ...] = ()
    body: str = ""
    comments: int = 0
    assignee: str | None = None
    state: str = "open"
    amount: Amount | None = None
    language: str | None = None
    stars: int | None = None
    is_fork: bool = False
    # Why somebody else is likely to land this first. None means nobody is.
    claim_reason: str | None = None

    @property
    def key(self) -> str:
        return f"{self.repo}#{self.number}"

    @property
    def claimed(self) -> bool:
        return self.claim_reason is not None

    def age_days(self, as_of: datetime) -> float:
        return (as_of - self.created_at).total_seconds() / 86400

    def stale_days(self, as_of: datetime) -> float:
        """Days since the issue last saw any activity."""
        return (as_of - self.updated_at).total_seconds() / 86400


@dataclass(frozen=True, slots=True)
class ScoredBounty:
    """A bounty with its score, and the reason to distrust it if there is one."""

    bounty: Bounty
    score: ScoreBreakdown
    suspect_reason: str | None = None
    triage: Triage = Triage()
    bounty_id: int | None = None

    @property
    def suspect(self) -> bool:
        return self.suspect_reason is not None
