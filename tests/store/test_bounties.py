import sqlite3
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from bounty_searcher.domain.models import AmountField, TriageStatus
from bounty_searcher.domain.scoring import ScoreWeights
from bounty_searcher.store.bounties import (
    BountyFilter,
    Cursor,
    SortKey,
    content_hash,
    counts,
    get,
    list_bounties,
    score_bounties,
    upsert_many,
)
from bounty_searcher.store.db import Database, to_ts
from bounty_searcher.store.triage import set_status
from tests.domain.builders import amount
from tests.store.corpus import NOW, WEIGHTS, bounty, fill


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with Database(tmp_path / "state.db") as db:
        yield db.conn


# -- writing ---------------------------------------------------------------


def test_upsert_reports_what_it_did(conn: sqlite3.Connection) -> None:
    result = upsert_many(conn, [bounty(1), bounty(2)], NOW)
    assert (result.inserted, result.changed) == (2, 0)
    assert len(result.ids) == 2


def test_first_seen_survives_a_rescan(conn: sqlite3.Connection) -> None:
    upsert_many(conn, [bounty(1)], NOW)
    later = NOW + timedelta(days=3)
    upsert_many(conn, [bounty(1)], later)

    row = conn.execute("SELECT first_seen_at, last_seen_at FROM bounty").fetchone()
    assert row["first_seen_at"] == to_ts(NOW)
    assert row["last_seen_at"] == to_ts(later)


def test_a_material_change_moves_changed_at(conn: sqlite3.Connection) -> None:
    upsert_many(conn, [bounty(1, title="Before")], NOW)
    later = NOW + timedelta(days=3)
    result = upsert_many(conn, [bounty(1, title="After")], later)

    assert (result.inserted, result.changed) == (0, 1)
    assert conn.execute("SELECT changed_at FROM bounty").fetchone()[0] == to_ts(later)


def test_seeing_the_same_issue_again_is_not_a_change(conn: sqlite3.Connection) -> None:
    upsert_many(conn, [bounty(1)], NOW)
    later = NOW + timedelta(days=3)
    result = upsert_many(conn, [bounty(1)], later)

    assert (result.inserted, result.changed) == (0, 0)
    assert conn.execute("SELECT changed_at FROM bounty").fetchone()[0] == to_ts(NOW)


def test_the_hash_ignores_when_we_looked(conn: sqlite3.Connection) -> None:
    assert content_hash(bounty(1)) == content_hash(bounty(1))
    assert content_hash(bounty(1)) != content_hash(bounty(1, comments=4))


def test_an_upsert_batch_is_all_or_nothing(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.Error):
        # A repo of the wrong type violates NOT NULL on the way in.
        upsert_many(conn, [bounty(1), bounty(2, repo=None)], NOW)
    assert conn.execute("SELECT COUNT(*) FROM bounty").fetchone()[0] == 0


# -- scoring ---------------------------------------------------------------


def test_scoring_writes_one_row_per_bounty(conn: sqlite3.Connection) -> None:
    upsert_many(conn, [bounty(1), bounty(2)], NOW)
    assert score_bounties(conn, WEIGHTS, NOW) == 2
    assert conn.execute("SELECT COUNT(*) FROM bounty_score").fetchone()[0] == 2


def test_rescoring_replaces_rather_than_duplicates(conn: sqlite3.Connection) -> None:
    fill(conn, [bounty(1)])
    before = conn.execute("SELECT total FROM bounty_score").fetchone()["total"]

    heavier = ScoreWeights(payout_max=80.0, preferred_languages=("typescript",))
    score_bounties(conn, heavier, NOW)

    rows = conn.execute("SELECT total, weights_hash FROM bounty_score").fetchall()
    assert len(rows) == 1
    assert rows[0]["total"] > before


def test_suspicion_is_stored_with_the_score(conn: sqlite3.Connection) -> None:
    fill(conn, [bounty(1, stars=0, amount=amount(900))])
    reason = conn.execute("SELECT suspect_reason FROM bounty_score").fetchone()[0]
    assert reason == "$900 from a 0-star repo"


def test_scoring_a_subset_leaves_the_rest_alone(conn: sqlite3.Connection) -> None:
    ids = fill(conn, [bounty(1), bounty(2)])
    assert score_bounties(conn, WEIGHTS, NOW, bounty_ids=[ids[0]]) == 1
    assert score_bounties(conn, WEIGHTS, NOW, bounty_ids=[]) == 0


# -- reading ---------------------------------------------------------------


def test_the_list_is_ordered_by_score(conn: sqlite3.Connection) -> None:
    fill(conn, [bounty(n) for n in range(1, 6)])
    page = list_bounties(conn, as_of=NOW)
    totals = [row.score.total for row in page.rows]
    assert totals == sorted(totals, reverse=True)
    assert page.total == 5


def test_a_page_carries_its_own_body_free_rows(conn: sqlite3.Connection) -> None:
    fill(conn, [bounty(1, body="a very long issue body")])
    page = list_bounties(conn, as_of=NOW)
    assert page.rows[0].bounty.body == ""

    full = get(conn, page.rows[0].bounty_id or 0)
    assert full is not None and full.bounty.body == "a very long issue body"


def test_a_fetched_bounty_keeps_its_provenance(conn: sqlite3.Connection) -> None:
    ids = fill(conn, [bounty(1)])
    fetched = get(conn, ids[0])
    assert fetched is not None and fetched.bounty.amount is not None
    assert fetched.bounty.amount.provenance.field is AmountField.LABEL
    assert fetched.bounty.amount.minor_units == 10_000


def test_fetching_a_bounty_that_is_not_there(conn: sqlite3.Connection) -> None:
    assert get(conn, 404) is None


def test_paging_walks_the_whole_corpus_without_repeating(
    conn: sqlite3.Connection,
) -> None:
    fill(conn, [bounty(n) for n in range(1, 26)])

    seen: list[int] = []
    cursor: Cursor | None = None
    while True:
        page = list_bounties(conn, as_of=NOW, limit=7, cursor=cursor)
        seen.extend(row.bounty_id or 0 for row in page.rows)
        cursor = page.next_cursor
        if cursor is None:
            break

    assert len(seen) == 25
    assert len(set(seen)) == 25


def test_pages_are_stable_while_rows_are_inserted(conn: sqlite3.Connection) -> None:
    """A scan running underneath triage must not shuffle what you are reading."""
    fill(conn, [bounty(n) for n in range(1, 11)])

    first = list_bounties(conn, as_of=NOW, limit=5)
    fill(conn, [bounty(n) for n in range(100, 110)])
    second = list_bounties(conn, as_of=NOW, limit=5, cursor=first.next_cursor)

    assert not {row.bounty_id for row in first.rows} & {
        row.bounty_id for row in second.rows
    }
    # Ordering still holds across the boundary.
    assert first.rows[-1].score.total >= second.rows[0].score.total


def test_sorting_by_payout(conn: sqlite3.Connection) -> None:
    fill(conn, [bounty(1), bounty(2), bounty(3, amount=None)])
    page = list_bounties(conn, as_of=NOW, sort=SortKey.PAYOUT)
    payouts = [
        row.bounty.amount.minor_units if row.bounty.amount else -1 for row in page.rows
    ]
    assert payouts == sorted(payouts, reverse=True)


def test_sorting_by_first_seen(conn: sqlite3.Connection) -> None:
    fill(conn, [bounty(1)], now=NOW - timedelta(days=5))
    fill(conn, [bounty(2)], now=NOW)
    page = list_bounties(conn, as_of=NOW, sort=SortKey.NEWEST)
    assert [row.bounty.number for row in page.rows] == [2, 1]


def test_paging_by_payout_is_also_stable(conn: sqlite3.Connection) -> None:
    fill(conn, [bounty(n) for n in range(1, 10)] + [bounty(20, amount=None)])
    first = list_bounties(conn, as_of=NOW, sort=SortKey.PAYOUT, limit=4)
    second = list_bounties(
        conn, as_of=NOW, sort=SortKey.PAYOUT, limit=4, cursor=first.next_cursor
    )
    assert not {row.bounty_id for row in first.rows} & {
        row.bounty_id for row in second.rows
    }


# -- filtering -------------------------------------------------------------


def test_filtering_by_language(conn: sqlite3.Connection) -> None:
    fill(conn, [bounty(1, language="Rust"), bounty(2, language="TypeScript")])
    page = list_bounties(conn, as_of=NOW, filters=BountyFilter(language="rust"))
    assert page.total == 1
    assert page.rows[0].bounty.number == 1


def test_filtering_by_minimum_payout_hides_unpriced_rows(
    conn: sqlite3.Connection,
) -> None:
    fill(
        conn,
        [
            bounty(1, amount=amount(50)),
            bounty(2, amount=amount(900)),
            bounty(3, amount=None),
        ],
    )
    page = list_bounties(conn, as_of=NOW, filters=BountyFilter(min_amount_minor=10_000))
    assert [row.bounty.number for row in page.rows] == [2]


def test_filtering_by_stars_and_age(conn: sqlite3.Connection) -> None:
    fill(
        conn,
        [
            bounty(1, stars=10),
            bounty(2, stars=9000),
            bounty(3, stars=9000, created_at=NOW - timedelta(days=400)),
        ],
    )
    page = list_bounties(
        conn, as_of=NOW, filters=BountyFilter(min_stars=1000, max_age_days=30)
    )
    assert [row.bounty.number for row in page.rows] == [2]


def test_suspect_rows_are_hidden_unless_asked_for(conn: sqlite3.Connection) -> None:
    fill(conn, [bounty(1, stars=0), bounty(2)])
    assert list_bounties(conn, as_of=NOW).total == 1
    assert (
        list_bounties(conn, as_of=NOW, filters=BountyFilter(include_suspect=True)).total
        == 2
    )


def test_claimed_rows_can_be_excluded(conn: sqlite3.Connection) -> None:
    fill(conn, [bounty(1, claim_reason="assigned to @someone"), bounty(2)])
    page = list_bounties(conn, as_of=NOW, filters=BountyFilter(include_claimed=False))
    assert [row.bounty.number for row in page.rows] == [2]


def test_text_search_matches_title_and_repo(conn: sqlite3.Connection) -> None:
    fill(
        conn,
        [
            bounty(1, title="Fix the flaky retry logic"),
            bounty(2, repo="acme/widgets", title="Something else"),
        ],
    )
    assert list_bounties(conn, as_of=NOW, filters=BountyFilter(text="flaky")).total == 1
    assert (
        list_bounties(conn, as_of=NOW, filters=BountyFilter(text="widgets")).total == 1
    )


def test_text_search_matches_a_partial_last_word(conn: sqlite3.Connection) -> None:
    fill(conn, [bounty(1, title="Fix the flaky retry logic")])
    assert list_bounties(conn, as_of=NOW, filters=BountyFilter(text="fla")).total == 1


def test_punctuation_in_a_search_is_not_a_syntax_error(
    conn: sqlite3.Connection,
) -> None:
    fill(conn, [bounty(1, title="Fix the flaky retry logic")])
    assert list_bounties(conn, as_of=NOW, filters=BountyFilter(text='"(bad')).total == 0


def test_the_index_follows_a_retitled_issue(conn: sqlite3.Connection) -> None:
    fill(conn, [bounty(1, title="Original title")])
    fill(conn, [bounty(1, title="Renamed entirely")])
    assert (
        list_bounties(conn, as_of=NOW, filters=BountyFilter(text="original")).total == 0
    )
    assert (
        list_bounties(conn, as_of=NOW, filters=BountyFilter(text="renamed")).total == 1
    )


def test_filters_combine(conn: sqlite3.Connection) -> None:
    fill(
        conn,
        [
            bounty(1, language="Rust", amount=amount(900)),
            bounty(2, language="Rust", amount=amount(50)),
            bounty(3, language="Go", amount=amount(900)),
        ],
    )
    page = list_bounties(
        conn,
        as_of=NOW,
        filters=BountyFilter(language="rust", min_amount_minor=10_000),
    )
    assert [row.bounty.number for row in page.rows] == [1]


def test_a_cursor_survives_being_encoded(conn: sqlite3.Connection) -> None:
    cursor = Cursor(61.5, 42)
    assert Cursor.decode(cursor.encode()) == cursor


def test_rows_carry_when_the_corpus_first_saw_them(conn: sqlite3.Connection) -> None:
    """The interface marks a new row, so the read has to say when it arrived."""
    fill(conn, [bounty(1)])
    later = NOW + timedelta(days=1)
    fill(conn, [bounty(1, title="Retitled"), bounty(2)], later)

    rows = {r.bounty.number: r for r in list_bounties(conn, as_of=later).rows}
    assert rows[1].first_seen_at == NOW
    assert rows[1].changed_at == later
    assert rows[2].first_seen_at == later


def test_counts_describe_the_whole_corpus(conn: sqlite3.Connection) -> None:
    ids = fill(conn, [bounty(1), bounty(2, amount=None), bounty(3, stars=0)])
    set_status(conn, [ids[0]], TriageStatus.SHORTLISTED, NOW)

    totals = counts(conn, NOW)
    assert (totals.total, totals.priced, totals.suspect) == (3, 2, 1)
    assert totals.by_status == {
        TriageStatus.SHORTLISTED: 1,
        TriageStatus.NEW: 2,
    }


def test_an_expired_snooze_is_counted_as_new_again(conn: sqlite3.Connection) -> None:
    ids = fill(conn, [bounty(1)])
    set_status(
        conn, list(ids), TriageStatus.SNOOZED, NOW, snooze_until=NOW + timedelta(days=1)
    )

    assert counts(conn, NOW).by_status == {TriageStatus.SNOOZED: 1}
    assert counts(conn, NOW + timedelta(days=2)).by_status == {TriageStatus.NEW: 1}
