"""Suspicion rules, ordering, and per-repo capping.

Scoring ranks bounties independently, which lets a single repo take over the
whole list: one project that files six near-identical "[Bug bounty]" issues on
the same day outranks six different opportunities from six repos. That is worse
for you even when the scores are honest, because your realistic move is to pick
one issue from that repo, not all six.
"""

from __future__ import annotations

from datetime import datetime

from .models import Bounty, ScoredBounty
from .scoring import ScoreWeights, score

_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£"}


def _money(bounty: Bounty) -> str:
    assert bounty.amount is not None
    symbol = _SYMBOLS.get(bounty.amount.currency, "")
    return f"{symbol}{bounty.amount.units:,.0f}"


def assess_suspicion(b: Bounty, w: ScoreWeights) -> str | None:
    """Why this payout probably isn't real money, or None if it looks fine.

    Two patterns dominate the noise on GitHub issue search: AI-spam repos that
    post enormous fake bounties to farm attention, and template repos cloned
    dozens of times with the same seeded "bounty" issue. Both are recognisable
    by a large advertised payout attached to a repo with no stars.
    """
    if b.amount is None:
        return None

    stars = b.stars if b.stars is not None else 0

    # Money advertised by a repo nobody has starred is the single strongest
    # spam signal, at any amount: the farming repos post $200 as readily as
    # $50,000. Legitimate brand-new projects get caught here too, which is what
    # the include-suspect switch is for.
    if stars < w.credible_stars:
        return f"{_money(b)} from a {stars}-star repo"
    if b.amount.scale >= w.absurd_payout and stars < w.absurd_needs_stars:
        return f"{_money(b)} is implausible for {stars:,} stars"
    return None


def rank(
    bounties: list[Bounty], w: ScoreWeights, as_of: datetime
) -> list[ScoredBounty]:
    """Assess, score and order a set of bounties, best first."""
    scored = []
    for b in bounties:
        suspect_reason = assess_suspicion(b, w)
        scored.append(
            ScoredBounty(
                bounty=b,
                score=score(b, w, as_of, suspect=suspect_reason is not None),
                suspect_reason=suspect_reason,
            )
        )
    return sorted(scored, key=lambda s: s.score.total, reverse=True)


def cap_per_repo(
    bounties: list[ScoredBounty], cap: int
) -> tuple[list[ScoredBounty], dict[str, int]]:
    """Keep at most `cap` bounties per repo, best-scoring first.

    Expects `bounties` already sorted by descending score, so the survivors are
    each repo's strongest entries. A cap of 0 (or less) disables the rule.

    Returns the kept list plus a ``{repo: number_dropped}`` map, so the caller
    can tell you what it collapsed instead of silently truncating.
    """
    if cap <= 0:
        return bounties, {}

    kept: list[ScoredBounty] = []
    seen: dict[str, int] = {}
    dropped: dict[str, int] = {}

    for s in bounties:
        repo = s.bounty.repo
        count = seen.get(repo, 0)
        if count < cap:
            kept.append(s)
            seen[repo] = count + 1
        else:
            dropped[repo] = dropped.get(repo, 0) + 1

    return kept, dropped
