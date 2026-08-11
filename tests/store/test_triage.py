import sqlite3
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from bounty_searcher.domain.models import TriageStatus
from bounty_searcher.store import triage
from bounty_searcher.store.bounties import BountyFilter, list_bounties
from bounty_searcher.store.db import Database
from tests.store.corpus import NOW, bounty, fill


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with Database(tmp_path / "state.db") as db:
        yield db.conn


def test_an_untouched_bounty_is_new(conn: sqlite3.Connection) -> None:
    ids = fill(conn, [bounty(1)])
    assert triage.get(conn, ids[0]).status is TriageStatus.NEW


def test_a_transition_is_recorded(conn: sqlite3.Connection) -> None:
    ids = fill(conn, [bounty(1)])
    triage.set_status(conn, [ids[0]], TriageStatus.SHORTLISTED, NOW)

    stored = triage.get(conn, ids[0])
    assert stored.status is TriageStatus.SHORTLISTED
    assert stored.updated_at == NOW


def test_snoozing_stores_its_expiry(conn: sqlite3.Connection) -> None:
    ids = fill(conn, [bounty(1)])
    wakes = NOW + timedelta(days=7)
    triage.set_status(conn, [ids[0]], TriageStatus.SNOOZED, NOW, snooze_until=wakes)

    stored = triage.get(conn, ids[0])
    assert stored.snooze_until == wakes
    assert stored.effective_status(NOW) is TriageStatus.SNOOZED
    assert stored.effective_status(wakes + timedelta(seconds=1)) is TriageStatus.NEW


def test_undo_restores_the_previous_status(conn: sqlite3.Connection) -> None:
    ids = fill(conn, [bounty(1)])
    triage.set_status(conn, [ids[0]], TriageStatus.SHORTLISTED, NOW)
    token = triage.set_status(conn, [ids[0]], TriageStatus.DISMISSED, NOW)

    assert triage.undo(conn, token, NOW) == [ids[0]]
    assert triage.get(conn, ids[0]).status is TriageStatus.SHORTLISTED


def test_a_run_of_dismissals_comes_back_together(conn: sqlite3.Connection) -> None:
    """Holding the dismiss key is one gesture, so it is one undo."""
    ids = fill(conn, [bounty(n) for n in range(1, 6)])
    token = triage.set_status(conn, list(ids), TriageStatus.DISMISSED, NOW)

    assert sorted(triage.undo(conn, token, NOW)) == sorted(ids)
    for bounty_id in ids:
        assert triage.get(conn, bounty_id).status is TriageStatus.NEW


def test_undoing_twice_changes_nothing_the_second_time(
    conn: sqlite3.Connection,
) -> None:
    ids = fill(conn, [bounty(1)])
    token = triage.set_status(conn, [ids[0]], TriageStatus.DISMISSED, NOW)

    assert triage.undo(conn, token, NOW) == [ids[0]]
    assert triage.undo(conn, token, NOW) == []
    assert triage.get(conn, ids[0]).status is TriageStatus.NEW


def test_undo_last_takes_the_most_recent_transition(conn: sqlite3.Connection) -> None:
    ids = fill(conn, [bounty(1), bounty(2)])
    triage.set_status(conn, [ids[0]], TriageStatus.SHORTLISTED, NOW)
    triage.set_status(conn, [ids[1]], TriageStatus.DISMISSED, NOW)

    assert triage.undo_last(conn, NOW) == [ids[1]]
    assert triage.get(conn, ids[0]).status is TriageStatus.SHORTLISTED
    assert triage.get(conn, ids[1]).status is TriageStatus.NEW


def test_undo_last_walks_backwards_through_the_journal(
    conn: sqlite3.Connection,
) -> None:
    ids = fill(conn, [bounty(1)])
    triage.set_status(conn, [ids[0]], TriageStatus.SHORTLISTED, NOW)
    triage.set_status(conn, [ids[0]], TriageStatus.APPLIED, NOW)

    triage.undo_last(conn, NOW)
    assert triage.get(conn, ids[0]).status is TriageStatus.SHORTLISTED
    triage.undo_last(conn, NOW)
    assert triage.get(conn, ids[0]).status is TriageStatus.NEW
    assert triage.undo_last(conn, NOW) == []


def test_undoing_a_snooze_puts_its_expiry_back(conn: sqlite3.Connection) -> None:
    ids = fill(conn, [bounty(1)])
    wakes = NOW + timedelta(days=7)
    triage.set_status(conn, [ids[0]], TriageStatus.SNOOZED, NOW, snooze_until=wakes)
    token = triage.set_status(conn, [ids[0]], TriageStatus.DISMISSED, NOW)

    triage.undo(conn, token, NOW)
    stored = triage.get(conn, ids[0])
    assert stored.status is TriageStatus.SNOOZED
    assert stored.snooze_until == wakes


def test_the_journal_keeps_every_transition(conn: sqlite3.Connection) -> None:
    ids = fill(conn, [bounty(1)])
    triage.set_status(conn, [ids[0]], TriageStatus.SHORTLISTED, NOW)
    triage.set_status(conn, [ids[0]], TriageStatus.APPLIED, NOW)

    count = conn.execute("SELECT COUNT(*) FROM triage_journal").fetchone()[0]
    assert count == 2


def test_deleting_a_bounty_takes_its_triage_with_it(conn: sqlite3.Connection) -> None:
    ids = fill(conn, [bounty(1)])
    triage.set_status(conn, [ids[0]], TriageStatus.SHORTLISTED, NOW)
    conn.execute("DELETE FROM bounty WHERE id = ?", (ids[0],))

    assert conn.execute("SELECT COUNT(*) FROM triage").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM triage_journal").fetchone()[0] == 0


# -- what the corpus makes of a decision -----------------------------------


def test_filtering_the_corpus_by_triage_status(conn: sqlite3.Connection) -> None:
    ids = fill(conn, [bounty(1), bounty(2)])
    triage.set_status(conn, [ids[0]], TriageStatus.SHORTLISTED, NOW)

    shortlisted = list_bounties(
        conn, as_of=NOW, filters=BountyFilter(statuses=(TriageStatus.SHORTLISTED,))
    )
    assert [row.bounty_id for row in shortlisted.rows] == [ids[0]]

    untouched = list_bounties(
        conn, as_of=NOW, filters=BountyFilter(statuses=(TriageStatus.NEW,))
    )
    assert [row.bounty_id for row in untouched.rows] == [ids[1]]


def test_an_expired_snooze_reads_as_new_again(conn: sqlite3.Connection) -> None:
    """The whole point of snoozing: it comes back rather than being lost."""
    ids = fill(conn, [bounty(1)])
    triage.set_status(
        conn, [ids[0]], TriageStatus.SNOOZED, NOW, snooze_until=NOW + timedelta(days=7)
    )

    is_new = BountyFilter(statuses=(TriageStatus.NEW,))
    assert list_bounties(conn, as_of=NOW, filters=is_new).total == 0
    assert list_bounties(conn, as_of=NOW + timedelta(days=8), filters=is_new).total == 1


def test_a_decision_travels_with_the_bounty(conn: sqlite3.Connection) -> None:
    ids = fill(conn, [bounty(1)])
    triage.set_status(conn, [ids[0]], TriageStatus.APPLIED, NOW)

    page = list_bounties(conn, as_of=NOW)
    assert page.rows[0].triage.status is TriageStatus.APPLIED
