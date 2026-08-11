from datetime import UTC, datetime, timedelta
from typing import Any

from bounty_searcher.models import Bounty
from bounty_searcher.scoring import ScoreWeights, score_all, score_bounty


def make(**kwargs: Any) -> Bounty:
    now = datetime.now(UTC)
    defaults: dict[str, Any] = {
        "source": "test",
        "repo": "owner/repo",
        "number": 1,
        "title": "Fix a thing",
        "url": "https://example.com",
        "created_at": now - timedelta(days=2),
        "updated_at": now - timedelta(days=1),
        "stars": 500,
        "language": "TypeScript",
    }
    defaults.update(kwargs)
    return Bounty(**defaults)


WEIGHTS = ScoreWeights(preferred_languages=["typescript"])


def test_bigger_payout_scores_higher() -> None:
    small = score_bounty(make(amount=100), WEIGHTS)
    large = score_bounty(make(amount=1000), WEIGHTS)
    assert large > small


def test_payout_has_diminishing_returns() -> None:
    """Doubling a large payout should matter far less than doubling a small one."""
    gain_small = score_bounty(make(amount=200), WEIGHTS) - score_bounty(
        make(amount=100), WEIGHTS
    )
    gain_large = score_bounty(make(amount=4000), WEIGHTS) - score_bounty(
        make(amount=2000), WEIGHTS
    )
    assert gain_large < gain_small


def test_claimed_is_heavily_penalised() -> None:
    open_issue = score_bounty(make(amount=300), WEIGHTS)
    claimed = score_bounty(make(amount=300, claimed=True), WEIGHTS)
    assert claimed < open_issue - 30


def test_language_match_beats_mismatch() -> None:
    match = score_bounty(make(amount=200, language="TypeScript"), WEIGHTS)
    other = score_bounty(make(amount=200, language="Haskell"), WEIGHTS)
    assert match > other


def test_crowded_thread_is_demoted() -> None:
    quiet = score_bounty(make(amount=300, comments=0), WEIGHTS)
    busy = score_bounty(make(amount=300, comments=20), WEIGHTS)
    assert busy < quiet


def test_fresh_beats_stale() -> None:
    now = datetime.now(UTC)
    fresh = score_bounty(make(amount=300, created_at=now - timedelta(hours=6)), WEIGHTS)
    old = score_bounty(make(amount=300, created_at=now - timedelta(days=200)), WEIGHTS)
    assert fresh > old


def test_spam_payout_is_flagged_and_scores_below_a_modest_real_one() -> None:
    """The failure that motivated the filter: a fake $50k outranking a real $500."""
    spam = make(amount=50_000, stars=0)
    real = make(amount=500, stars=254)
    ranked = score_all([spam, real], WEIGHTS)
    assert spam.suspect and not real.suspect
    assert ranked[0] is real


def test_absurd_payout_on_a_mid_size_repo_is_flagged() -> None:
    b = make(amount=40_000, stars=200)
    score_bounty(b, WEIGHTS)
    assert b.suspect


def test_forks_are_demoted() -> None:
    original = score_bounty(make(amount=300), WEIGHTS)
    fork = score_bounty(make(amount=300, is_fork=True), WEIGHTS)
    assert fork < original


def test_score_stays_in_range() -> None:
    for b in (
        make(amount=99_000, stars=0, comments=500, claimed=True),
        make(amount=5000),
    ):
        assert 0.0 <= score_bounty(b, WEIGHTS) <= 100.0


def test_low_effort_labels_help() -> None:
    plain = score_bounty(make(amount=200), WEIGHTS)
    easy = score_bounty(make(amount=200, labels=["good first issue"]), WEIGHTS)
    assert easy > plain
