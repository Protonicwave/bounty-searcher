"""Post-scoring selection rules.

Scoring ranks bounties independently, which lets a single repo take over the
whole list -- one project that files six near-identical "[Bug bounty]" issues
on the same day outranks six different opportunities from six repos. That's
worse for you even when the scores are honest, because your realistic move is
to pick one issue from that repo, not all six.
"""

from __future__ import annotations

from .models import Bounty


def cap_per_repo(
    bounties: list[Bounty], cap: int
) -> tuple[list[Bounty], dict[str, int]]:
    """Keep at most `cap` bounties per repo, best-scoring first.

    Expects `bounties` already sorted by descending score, so the survivors are
    each repo's strongest entries. A cap of 0 (or less) disables the rule.

    Returns the kept list plus a ``{repo: number_dropped}`` map, so the caller
    can tell you what it collapsed instead of silently truncating.
    """
    if cap <= 0:
        return bounties, {}

    kept: list[Bounty] = []
    seen: dict[str, int] = {}
    dropped: dict[str, int] = {}

    for b in bounties:
        count = seen.get(b.repo, 0)
        if count < cap:
            kept.append(b)
            seen[b.repo] = count + 1
        else:
            dropped[b.repo] = dropped.get(b.repo, 0) + 1

    return kept, dropped


def describe_dropped(dropped: dict[str, int], cap: int) -> str:
    """One-line summary of what the cap collapsed, busiest repo first."""
    if not dropped:
        return ""

    ranked = sorted(dropped.items(), key=lambda kv: -kv[1])
    total = sum(dropped.values())
    shown = ", ".join(f"{repo} (+{n})" for repo, n in ranked[:3])
    if len(ranked) > 3:
        shown += f", and {len(ranked) - 3} more"
    return f"{total} collapsed by --per-repo {cap}: {shown}"
