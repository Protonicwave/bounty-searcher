"""Ranking bounties by winnability, not by payout.

A $2,000 bounty on a compiler internals bug in a 90k-star repo is worth less
to most people than a $150 bounty on a small CLI they can fix tonight. The
score reflects that: payout has hard diminishing returns, and the penalties
for age, crowding and prior claims are large enough to sink an expensive but
already-contested issue.

Every component is recorded in `score_parts` so `--explain` can show its work.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Bounty

# Labels suggesting the fix is small and well-specified.
LOW_EFFORT_LABELS = {
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

# Labels suggesting an open-ended design problem.
HIGH_EFFORT_LABELS = {
    "epic",
    "rfc",
    "proposal",
    "discussion",
    "research",
    "architecture",
    "breaking change",
    "help wanted: expert",
}


@dataclass
class ScoreWeights:
    """Tunable knobs -- overridable from config.toml."""

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
    preferred_languages: list[str] = field(default_factory=list)


def flag_suspect(b: Bounty, w: ScoreWeights) -> None:
    """Mark payouts that almost certainly aren't real money.

    Two patterns dominate the noise on GitHub issue search: AI-spam repos that
    post enormous fake bounties to farm attention, and template repos cloned
    dozens of times with the same seeded "bounty" issue. Both are recognisable
    by a large advertised payout attached to a repo with no stars.
    """
    if not b.amount:
        return

    stars = b.stars if b.stars is not None else 0

    # Money advertised by a repo nobody has starred is the single strongest
    # spam signal, at any amount -- the farming repos post $200 as readily as
    # $50,000. Legitimate brand-new projects get caught here too, which is what
    # --include-suspect is for.
    if stars < w.credible_stars:
        b.suspect = True
        b.suspect_reason = f"${b.amount:,.0f} from a {stars}-star repo"
    elif b.amount >= w.absurd_payout and stars < w.absurd_needs_stars:
        b.suspect = True
        b.suspect_reason = f"${b.amount:,.0f} is implausible for {stars} stars"


def score_bounty(b: Bounty, w: ScoreWeights) -> float:
    parts: dict[str, float] = {}
    flag_suspect(b, w)

    # Payout, with diminishing returns: at `payout_halfway` you get half the
    # maximum, and it asymptotes rather than letting one huge number dominate.
    if b.amount and not b.suspect:
        parts["payout"] = w.payout_max * (b.amount / (b.amount + w.payout_halfway))
    elif b.suspect:
        # An unverifiable payout is worth nothing, so it earns nothing -- it
        # must not outrank a modest bounty from a repo that actually pays.
        parts["payout"] = -w.unpriced_penalty
    else:
        parts["payout"] = -w.unpriced_penalty

    # Language fit.
    prefs = {lang.lower() for lang in w.preferred_languages}
    if prefs:
        if b.language and b.language.lower() in prefs:
            parts["language"] = w.language_match
        elif b.language is None:
            parts["language"] = w.language_unknown
        else:
            parts["language"] = 0.0

    # Effort proxy from labels.
    labels = {l.lower() for l in b.labels}
    effort = 0.0
    if labels & LOW_EFFORT_LABELS:
        effort += w.low_effort
    if labels & HIGH_EFFORT_LABELS:
        effort += w.high_effort
    if "help wanted" in labels or "help-wanted" in labels:
        effort += w.help_wanted
    if effort:
        parts["effort"] = effort

    # Freshness: newest issues are the ones you can still win.
    age = b.age_days
    if age < w.freshness_zero_days:
        parts["freshness"] = w.freshness_max * (1 - age / w.freshness_zero_days)

    # Crowding: every comment is someone else who has looked at this.
    if b.comments:
        parts["competition"] = -min(
            b.comments * w.comment_penalty_each, w.comment_penalty_cap
        )

    # Abandoned threads rarely pay out.
    if b.stale_days > w.stale_after_days:
        parts["stale"] = -w.stale_penalty

    # Repo size: mid-size repos merge outside PRs fastest.
    if b.stars is not None:
        lo, hi = w.sweet_spot_stars
        if lo <= b.stars <= hi:
            parts["repo_size"] = w.sweet_spot_bonus
        elif b.stars > w.crowded_stars:
            parts["repo_size"] = -w.crowded_penalty
        elif b.stars < w.credible_stars:
            parts["repo_size"] = -w.no_stars_penalty

    # Cloned template repos seed the same fake "bounty" issue in every copy.
    if b.is_fork:
        parts["fork"] = -w.fork_penalty

    if b.claimed:
        parts["claimed"] = -w.claimed_penalty

    total = sum(parts.values())
    b.score_parts = parts
    b.score = max(0.0, min(100.0, total + 30.0))  # +30 keeps typical scores positive
    return b.score


def score_all(bounties: list[Bounty], w: ScoreWeights) -> list[Bounty]:
    for b in bounties:
        score_bounty(b, w)
    return sorted(bounties, key=lambda b: b.score, reverse=True)
