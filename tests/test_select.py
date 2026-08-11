from datetime import datetime, timezone

from bounty_searcher.models import Bounty
from bounty_searcher.select import cap_per_repo, describe_dropped


def make(repo: str, score: float, number: int = 1) -> Bounty:
    now = datetime.now(timezone.utc)
    b = Bounty(
        source="test",
        repo=repo,
        number=number,
        title="t",
        url="https://example.com",
        created_at=now,
        updated_at=now,
    )
    b.score = score
    return b


def test_cap_keeps_best_scoring_per_repo():
    """The scenario that motivated this: one repo filing six near-identical issues."""
    spam = [make("noisy/repo", 90 - i, number=i) for i in range(6)]
    others = [make("other/one", 50), make("other/two", 40)]
    kept, dropped = cap_per_repo(spam + others, cap=3)

    assert [b.repo for b in kept].count("noisy/repo") == 3
    # Highest-scoring three survive, in order.
    assert [b.score for b in kept if b.repo == "noisy/repo"] == [90, 89, 88]
    assert dropped == {"noisy/repo": 3}


def test_other_repos_are_untouched():
    items = [make("a/a", 90), make("b/b", 80), make("c/c", 70)]
    kept, dropped = cap_per_repo(items, cap=3)
    assert kept == items
    assert dropped == {}


def test_cap_of_zero_disables_the_rule():
    items = [make("a/a", 90, i) for i in range(5)]
    kept, dropped = cap_per_repo(items, cap=0)
    assert len(kept) == 5
    assert dropped == {}


def test_negative_cap_also_disables():
    items = [make("a/a", 90, i) for i in range(5)]
    assert len(cap_per_repo(items, cap=-1)[0]) == 5


def test_cap_of_one_leaves_a_single_entry_per_repo():
    items = [make("a/a", 90), make("a/a", 80, 2), make("b/b", 70)]
    kept, _ = cap_per_repo(items, cap=1)
    assert [(b.repo, b.score) for b in kept] == [("a/a", 90.0), ("b/b", 70.0)]


def test_relative_order_is_preserved():
    items = [make("a/a", 90), make("b/b", 85), make("a/a", 80, 2), make("b/b", 75, 2)]
    kept, _ = cap_per_repo(items, cap=2)
    assert [b.score for b in kept] == [90, 85, 80, 75]


def test_describe_dropped_is_empty_when_nothing_dropped():
    assert describe_dropped({}, 3) == ""


def test_describe_dropped_ranks_busiest_first():
    note = describe_dropped({"small/one": 1, "big/one": 9}, 3)
    assert note.startswith("10 collapsed by --per-repo 3: big/one (+9)")


def test_describe_dropped_truncates_long_lists():
    note = describe_dropped({f"r/{i}": 1 for i in range(6)}, 2)
    assert "and 3 more" in note
