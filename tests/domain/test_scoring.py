from datetime import timedelta

from bounty_searcher.domain.models import Bounty, ScoreComponent
from bounty_searcher.domain.scoring import (
    ScoreWeights,
    component_maxima,
    score,
    weights_hash,
)
from tests.domain.builders import NOW, amount, bounty

WEIGHTS = ScoreWeights(preferred_languages=("typescript",))


def total(b: Bounty, *, suspect: bool = False) -> float:
    return score(b, WEIGHTS, NOW, suspect=suspect).total


def test_bigger_payout_scores_higher() -> None:
    assert total(bounty(amount=amount(1000))) > total(bounty(amount=amount(100)))


def test_payout_has_diminishing_returns() -> None:
    """Doubling a large payout should matter far less than doubling a small one."""
    gain_small = total(bounty(amount=amount(200))) - total(bounty(amount=amount(100)))
    gain_large = total(bounty(amount=amount(4000))) - total(bounty(amount=amount(2000)))
    assert gain_large < gain_small


def test_claimed_is_heavily_penalised() -> None:
    open_issue = total(bounty(amount=amount(300)))
    claimed = total(bounty(amount=amount(300), claim_reason="assigned to @someone"))
    assert claimed < open_issue - 30


def test_language_match_beats_mismatch() -> None:
    match = total(bounty(amount=amount(200), language="TypeScript"))
    other = total(bounty(amount=amount(200), language="Haskell"))
    assert match > other


def test_crowded_thread_is_demoted() -> None:
    assert total(bounty(amount=amount(300), comments=20)) < total(
        bounty(amount=amount(300), comments=0)
    )


def test_fresh_beats_stale() -> None:
    fresh = total(bounty(amount=amount(300), created_at=NOW - timedelta(hours=6)))
    old = total(bounty(amount=amount(300), created_at=NOW - timedelta(days=200)))
    assert fresh > old


def test_a_suspect_payout_earns_nothing() -> None:
    """The failure that motivated the filter: a fake $50k outranking a real $500."""
    fake = total(bounty(amount=amount(50_000), stars=0), suspect=True)
    real = total(bounty(amount=amount(500), stars=254))
    assert real > fake


def test_forks_are_demoted() -> None:
    assert total(bounty(amount=amount(300), is_fork=True)) < total(
        bounty(amount=amount(300))
    )


def test_score_stays_in_range() -> None:
    worst = bounty(
        amount=amount(99_000),
        stars=0,
        comments=500,
        claim_reason="taken",
    )
    assert 0.0 <= total(worst, suspect=True) <= 100.0
    assert 0.0 <= total(bounty(amount=amount(5000))) <= 100.0


def test_low_effort_labels_help() -> None:
    assert total(bounty(amount=amount(200), labels=("good first issue",))) > total(
        bounty(amount=amount(200))
    )


def test_scoring_is_the_same_at_the_same_moment() -> None:
    """Nothing reads the clock, so the same inputs give the same answer."""
    b = bounty(amount=amount(300))
    assert score(b, WEIGHTS, NOW).total == score(b, WEIGHTS, NOW).total


def test_every_component_is_reported_once() -> None:
    breakdown = score(bounty(amount=amount(300)), WEIGHTS, NOW)
    reported = [part.component for part in breakdown.components]
    assert reported == list(ScoreComponent)


def test_components_and_base_add_up_to_the_total() -> None:
    breakdown = score(bounty(amount=amount(300)), WEIGHTS, NOW)
    parts = sum(part.value for part in breakdown.components)
    assert breakdown.total == breakdown.base + parts


def test_maxima_bound_the_values_they_describe() -> None:
    breakdown = score(bounty(amount=amount(1_000_000)), WEIGHTS, NOW)
    for part in breakdown.components:
        assert part.value <= part.maximum


def test_weights_hash_tracks_the_weights() -> None:
    assert weights_hash(WEIGHTS) == weights_hash(
        ScoreWeights(preferred_languages=("typescript",))
    )
    assert weights_hash(WEIGHTS) != weights_hash(
        ScoreWeights(payout_max=99.0, preferred_languages=("typescript",))
    )


def test_the_hash_is_carried_on_the_breakdown() -> None:
    assert score(bounty(), WEIGHTS, NOW).weights_hash == weights_hash(WEIGHTS)


def test_the_maxima_on_a_breakdown_are_the_ones_published() -> None:
    """One definition, so a rail drawn to scale agrees with the score it drew."""
    breakdown = score(bounty(), WEIGHTS, NOW)
    maxima = component_maxima(WEIGHTS)

    assert {part.component: part.maximum for part in breakdown.components} == maxima


def test_language_can_only_score_when_a_language_is_preferred() -> None:
    assert component_maxima(ScoreWeights())[ScoreComponent.LANGUAGE] == 0.0
    assert component_maxima(WEIGHTS)[ScoreComponent.LANGUAGE] > 0.0
