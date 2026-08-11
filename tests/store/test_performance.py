"""Budgets, not benchmarks.

These assert the numbers the design depends on: that a weight change re-scores
the whole corpus locally in a moment, and that a page comes back without a
table scan. They are deliberately loose, because a machine under load should
not fail a build, and deliberately present, because "it feels fast" is how a
tool ends up unusable at ten thousand rows.
"""

import gc
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from bounty_searcher.store.bounties import (
    BountyFilter,
    SortKey,
    list_bounties,
    score_bounties,
)
from bounty_searcher.store.db import Database
from tests.conftest import CORPUS_SIZE
from tests.store.corpus import NOW, WEIGHTS

RESCORE_BUDGET_SECONDS = 2.0
# Enough passes to get one that the rest of the session is not interfering with.
RESCORE_ATTEMPTS = 3


@pytest.fixture(scope="module")
def corpus(large_corpus: Path) -> Iterator[sqlite3.Connection]:
    """Our own connection to the session's corpus."""
    with Database(large_corpus) as db:
        yield db.conn


def test_the_corpus_is_the_size_the_budgets_assume(corpus: sqlite3.Connection) -> None:
    assert corpus.execute("SELECT COUNT(*) FROM bounty").fetchone()[0] == CORPUS_SIZE


def test_rescoring_the_whole_corpus_is_a_local_pass(
    corpus: sqlite3.Connection,
) -> None:
    """The fastest of several passes, which is what the code can actually do.

    A single timing here measures the rest of the test session as much as it
    measures the re-score: whatever ran before this left the heap full and the
    caches cold. Taking the best run removes that without loosening the number
    it has to beat.
    """
    gc.collect()
    runs = []
    for _ in range(RESCORE_ATTEMPTS):
        started = time.perf_counter()
        written = score_bounties(corpus, WEIGHTS, NOW)
        runs.append(time.perf_counter() - started)
        assert written == CORPUS_SIZE

    best = min(runs)
    assert best < RESCORE_BUDGET_SECONDS, (
        f"re-score took {best:.2f}s at best, of {[f'{r:.2f}' for r in runs]}"
    )


@pytest.mark.parametrize(
    ("order", "index"),
    [
        ("s.total DESC, s.bounty_id DESC", "bounty_score_ranked"),
        ("b.first_seen_at DESC, b.id DESC", "bounty_first_seen"),
        ("b.amount_minor DESC, b.id DESC", "bounty_amount"),
    ],
)
def test_every_sort_reads_an_index_rather_than_sorting(
    corpus: sqlite3.Connection, order: str, index: str
) -> None:
    """Ordering must not fall back to a sort over the whole corpus.

    This is also what justifies each index: one sort, one index, and no index
    that nothing reads.
    """
    plan = " ".join(
        row["detail"]
        for row in corpus.execute(
            "EXPLAIN QUERY PLAN"
            " SELECT b.id FROM bounty b JOIN bounty_score s ON s.bounty_id = b.id"
            f" ORDER BY {order} LIMIT 50"
        )
    )
    assert index in plan
    assert "TEMP B-TREE" not in plan


def test_paging_deep_into_the_corpus_stays_quick(corpus: sqlite3.Connection) -> None:
    started = time.perf_counter()
    cursor = None
    for _ in range(20):
        page = list_bounties(
            corpus,
            as_of=NOW,
            limit=50,
            cursor=cursor,
            filters=BountyFilter(include_suspect=True),
        )
        cursor = page.next_cursor
    elapsed = time.perf_counter() - started

    assert cursor is not None
    assert elapsed < 2.0, f"20 pages took {elapsed:.2f}s"


def test_a_filtered_page_over_the_whole_corpus_stays_quick(
    corpus: sqlite3.Connection,
) -> None:
    started = time.perf_counter()
    page = list_bounties(
        corpus,
        as_of=NOW,
        limit=50,
        sort=SortKey.NEWEST,
        filters=BountyFilter(
            language="rust", min_stars=100, max_age_days=90, include_suspect=True
        ),
    )
    elapsed = time.perf_counter() - started

    assert page.total > 0
    assert elapsed < 1.0, f"filtered page took {elapsed:.2f}s"
