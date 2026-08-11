"""Core data types shared across sources, scoring and rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Bounty:
    """A single candidate bounty: one GitHub issue with money attached to it."""

    source: str
    repo: str  # "owner/name"
    number: int
    title: str
    url: str
    created_at: datetime
    updated_at: datetime
    labels: list[str] = field(default_factory=list)
    body: str = ""
    comments: int = 0
    assignee: str | None = None
    state: str = "open"

    amount: float | None = None
    currency: str = "USD"
    amount_source: str = ""  # where the number came from: label / title / body

    language: str | None = None
    stars: int | None = None
    is_fork: bool = False

    claimed: bool = False
    claim_reason: str = ""

    # Payout looks fabricated -- see scoring.flag_suspect.
    suspect: bool = False
    suspect_reason: str = ""

    score: float = 0.0
    score_parts: dict[str, float] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.repo}#{self.number}"

    @property
    def age_days(self) -> float:
        return (datetime.now(timezone.utc) - self.created_at).total_seconds() / 86400

    @property
    def stale_days(self) -> float:
        """Days since the issue last saw any activity."""
        return (datetime.now(timezone.utc) - self.updated_at).total_seconds() / 86400

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "source": self.source,
            "repo": self.repo,
            "number": self.number,
            "title": self.title,
            "url": self.url,
            "amount": self.amount,
            "currency": self.currency,
            "amount_source": self.amount_source,
            "language": self.language,
            "stars": self.stars,
            "is_fork": self.is_fork,
            "suspect": self.suspect,
            "suspect_reason": self.suspect_reason,
            "labels": self.labels,
            "comments": self.comments,
            "assignee": self.assignee,
            "claimed": self.claimed,
            "claim_reason": self.claim_reason,
            "age_days": round(self.age_days, 1),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "score": round(self.score, 1),
            "score_parts": {k: round(v, 1) for k, v in self.score_parts.items()},
        }
