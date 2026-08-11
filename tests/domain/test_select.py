from bounty_searcher.domain.models import ScoreBreakdown, ScoredBounty
from bounty_searcher.domain.scoring import ScoreWeights
from bounty_searcher.domain.select import assess_suspicion, cap_per_repo, rank
from tests.domain.builders import NOW, amount, bounty

WEIGHTS = ScoreWeights(preferred_languages=("typescript",))


def scored(repo: str, total: float, number: int = 1) -> ScoredBounty:
    return ScoredBounty(
        bounty=bounty(repo=repo, number=number),
        score=ScoreBreakdown(total=total, base=30.0, components=(), weights_hash="x"),
    )


def test_cap_keeps_best_scoring_per_repo() -> None:
    """The scenario that motivated this: one repo filing six near-identical issues."""
    spam = [scored("noisy/repo", 90 - i, number=i) for i in range(6)]
    others = [scored("other/one", 50), scored("other/two", 40)]
    kept, dropped = cap_per_repo(spam + others, cap=3)

    assert [s.bounty.repo for s in kept].count("noisy/repo") == 3
    # Highest-scoring three survive, in order.
    assert [s.score.total for s in kept if s.bounty.repo == "noisy/repo"] == [
        90,
        89,
        88,
    ]
    assert dropped == {"noisy/repo": 3}


def test_other_repos_are_untouched() -> None:
    items = [scored("a/a", 90), scored("b/b", 80), scored("c/c", 70)]
    kept, dropped = cap_per_repo(items, cap=3)
    assert kept == items
    assert dropped == {}


def test_cap_of_zero_disables_the_rule() -> None:
    items = [scored("a/a", 90, i) for i in range(5)]
    kept, dropped = cap_per_repo(items, cap=0)
    assert len(kept) == 5
    assert dropped == {}


def test_negative_cap_also_disables() -> None:
    items = [scored("a/a", 90, i) for i in range(5)]
    assert len(cap_per_repo(items, cap=-1)[0]) == 5


def test_cap_of_one_leaves_a_single_entry_per_repo() -> None:
    items = [scored("a/a", 90), scored("a/a", 80, 2), scored("b/b", 70)]
    kept, _ = cap_per_repo(items, cap=1)
    assert [(s.bounty.repo, s.score.total) for s in kept] == [
        ("a/a", 90.0),
        ("b/b", 70.0),
    ]


def test_relative_order_is_preserved() -> None:
    items = [
        scored("a/a", 90),
        scored("b/b", 85),
        scored("a/a", 80, 2),
        scored("b/b", 75, 2),
    ]
    kept, _ = cap_per_repo(items, cap=2)
    assert [s.score.total for s in kept] == [90, 85, 80, 75]


def test_money_from_an_unstarred_repo_is_suspect() -> None:
    reason = assess_suspicion(bounty(amount=amount(500), stars=0), WEIGHTS)
    assert reason == "$500 from a 0-star repo"


def test_an_absurd_payout_on_a_mid_size_repo_is_suspect() -> None:
    reason = assess_suspicion(bounty(amount=amount(40_000), stars=200), WEIGHTS)
    assert reason == "$40,000 is implausible for 200 stars"


def test_a_modest_payout_from_a_real_repo_is_not_suspect() -> None:
    assert assess_suspicion(bounty(amount=amount(500), stars=254), WEIGHTS) is None


def test_an_unpriced_bounty_cannot_be_suspect() -> None:
    assert assess_suspicion(bounty(stars=0), WEIGHTS) is None


def test_ranking_puts_a_real_payout_above_a_fabricated_one() -> None:
    fake = bounty(repo="spam/repo", amount=amount(50_000), stars=0)
    real = bounty(repo="real/repo", amount=amount(500), stars=254)
    ranked = rank([fake, real], WEIGHTS, NOW)

    assert ranked[0].bounty is real
    assert ranked[0].suspect_reason is None
    assert ranked[1].suspect_reason is not None


def test_ranking_leaves_its_input_alone() -> None:
    """Nothing in the domain mutates: the same list can be ranked twice."""
    items = [bounty(amount=amount(300))]
    first = rank(items, WEIGHTS, NOW)
    second = rank(items, WEIGHTS, NOW)
    assert first[0].score.total == second[0].score.total
