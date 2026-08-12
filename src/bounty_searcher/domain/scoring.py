"""Ranking bounties by winnability, not by payout.

A $2,000 bounty on a compiler internals bug in a 90k-star repo is worth less to
most people than a $150 bounty on a small CLI they can fix tonight. The score
reflects that: payout has hard diminishing returns, and the penalties for age,
crowding and prior claims are large enough to sink an expensive but already
contested issue.

Scoring is a pure pass over stored fields. Changing a weight re-scores the
whole corpus locally and never costs a request.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from functools import lru_cache
from hashlib import blake2b
from types import MappingProxyType

from .models import Bounty, ComponentScore, ScoreBreakdown, ScoreComponent

# Labels suggesting the fix is small and well-specified.
LOW_EFFORT_LABELS = frozenset(
    {
        "good first issue",
        "good-first-issue",
        "beginner",
        "easy",
        "starter",
        "documentation",
        "docs",
        "typo",
        "chore",
        "small",
        "e2e",
    }
)

# Labels suggesting an open-ended design problem.
HIGH_EFFORT_LABELS = frozenset(
    {
        "epic",
        "rfc",
        "proposal",
        "discussion",
        "research",
        "architecture",
        "breaking change",
        "help wanted: expert",
    }
)

# Scores are shifted up by this much so a typical bounty lands in positive
# territory rather than reading as a failure.
BASE_SCORE = 30.0


@dataclass(frozen=True, slots=True)
class ScoreWeights:
    """Tunable knobs, overridable from config.toml."""

    payout_max: float = 40.0
    payout_halfway: float = 300.0  # payout that earns half of payout_max
    language_match: float = 15.0
    language_unknown: float = -4.0
    low_effort: float = 12.0
    high_effort: float = -10.0
    help_wanted: float = 4.0
    freshness_max: float = 12.0
    freshness_zero_days: float = 60.0
    comment_penalty_each: float = 1.5
    comment_penalty_cap: float = 15.0
    claimed_penalty: float = 45.0
    stale_penalty: float = 8.0
    stale_after_days: float = 120.0
    unpriced_penalty: float = 12.0
    fork_penalty: float = 10.0
    # Credibility: a huge payout advertised by a repo nobody has starred is
    # almost always spam or an AI-generated filler issue, not money.
    credible_stars: int = 5
    absurd_payout: float = 10_000.0
    absurd_needs_stars: int = 1_000
    no_stars_penalty: float = 8.0
    sweet_spot_stars: tuple[int, int] = (100, 20_000)
    sweet_spot_bonus: float = 4.0
    crowded_stars: int = 50_000
    crowded_penalty: float = 3.0
    preferred_languages: tuple[str, ...] = ()


@lru_cache(maxsize=8)
def weights_hash(w: ScoreWeights) -> str:
    """Short stable identifier for a weight configuration.

    Stored alongside every score so a row scored under different weights can be
    spotted and refreshed without comparing every field.
    """
    payload = json.dumps(asdict(w), sort_keys=True, default=str)
    return blake2b(payload.encode(), digest_size=8).hexdigest()


def _payout(b: Bounty, w: ScoreWeights, suspect: bool) -> float:
    if b.amount is None or suspect:
        # An unverifiable payout is worth nothing, so it earns nothing. It must
        # not outrank a modest bounty from a repo that actually pays.
        return -w.unpriced_penalty
    # Diminishing returns: at `payout_halfway` you get half the maximum, and it
    # asymptotes rather than letting one huge number dominate.
    units = b.amount.scale
    return w.payout_max * (units / (units + w.payout_halfway))


def _language(b: Bounty, w: ScoreWeights) -> float:
    if not w.preferred_languages:
        return 0.0
    prefs = {lang.lower() for lang in w.preferred_languages}
    if b.language is None:
        return w.language_unknown
    return w.language_match if b.language.lower() in prefs else 0.0


def _effort(b: Bounty, w: ScoreWeights) -> float:
    labels = {label.lower() for label in b.labels}
    effort = 0.0
    if labels & LOW_EFFORT_LABELS:
        effort += w.low_effort
    if labels & HIGH_EFFORT_LABELS:
        effort += w.high_effort
    if labels & {"help wanted", "help-wanted"}:
        effort += w.help_wanted
    return effort


def _freshness(b: Bounty, w: ScoreWeights, as_of: datetime) -> float:
    value = 0.0
    age = b.age_days(as_of)
    if age < w.freshness_zero_days:
        # Newest issues are the ones you can still win.
        value += w.freshness_max * (1 - age / w.freshness_zero_days)
    if b.stale_days(as_of) > w.stale_after_days:
        # Abandoned threads rarely pay out.
        value -= w.stale_penalty
    return value


def _competition(b: Bounty, w: ScoreWeights) -> float:
    # Every comment is someone else who has looked at this.
    value = -min(b.comments * w.comment_penalty_each, w.comment_penalty_cap)
    if b.claimed:
        value -= w.claimed_penalty
    return value


def _repository(b: Bounty, w: ScoreWeights) -> float:
    value = 0.0
    if b.stars is not None:
        lo, hi = w.sweet_spot_stars
        if lo <= b.stars <= hi:
            # Mid-size repos merge outside PRs fastest.
            value += w.sweet_spot_bonus
        elif b.stars > w.crowded_stars:
            value -= w.crowded_penalty
        elif b.stars < w.credible_stars:
            value -= w.no_stars_penalty
    if b.is_fork:
        # Cloned template repos seed the same fake "bounty" issue in every copy.
        value -= w.fork_penalty
    return value


@lru_cache(maxsize=8)
def component_maxima(w: ScoreWeights) -> Mapping[ScoreComponent, float]:
    """The best each component could manage for a perfect bounty.

    A property of the weights and not of any one bounty, so it is not stored
    per row. Whoever draws a segment to scale, or writes "9 of a possible 15",
    asks here.

    Cached and read-only, because scoring the whole corpus asks 50,000 times
    for the same six numbers.
    """
    return MappingProxyType(
        {
            ScoreComponent.PAYOUT: w.payout_max,
            ScoreComponent.LANGUAGE: w.language_match if w.preferred_languages else 0.0,
            ScoreComponent.EFFORT: w.low_effort + w.help_wanted,
            ScoreComponent.FRESHNESS: w.freshness_max,
            # Competition and repository size can only ever cost you, apart
            # from the sweet-spot bonus.
            ScoreComponent.COMPETITION: 0.0,
            ScoreComponent.REPOSITORY: w.sweet_spot_bonus,
        }
    )


def score(
    b: Bounty, w: ScoreWeights, as_of: datetime, *, suspect: bool = False
) -> ScoreBreakdown:
    """Score one bounty as of a given moment.

    `suspect` comes from `select.assess_suspicion`. A payout nobody can verify
    earns nothing, so the caller has to have made that judgement first.
    """
    # Written out rather than looped: this runs once per row of the corpus, and
    # the intermediate mapping cost more than the six lines it saved.
    m = component_maxima(w)
    components = (
        ComponentScore(
            ScoreComponent.PAYOUT, _payout(b, w, suspect), m[ScoreComponent.PAYOUT]
        ),
        ComponentScore(
            ScoreComponent.LANGUAGE, _language(b, w), m[ScoreComponent.LANGUAGE]
        ),
        ComponentScore(ScoreComponent.EFFORT, _effort(b, w), m[ScoreComponent.EFFORT]),
        ComponentScore(
            ScoreComponent.FRESHNESS,
            _freshness(b, w, as_of),
            m[ScoreComponent.FRESHNESS],
        ),
        ComponentScore(
            ScoreComponent.COMPETITION,
            _competition(b, w),
            m[ScoreComponent.COMPETITION],
        ),
        ComponentScore(
            ScoreComponent.REPOSITORY, _repository(b, w), m[ScoreComponent.REPOSITORY]
        ),
    )
    total = BASE_SCORE + sum(part.value for part in components)

    return ScoreBreakdown(
        total=max(0.0, min(100.0, total)),
        base=BASE_SCORE,
        components=components,
        weights_hash=weights_hash(w),
    )
