"""The saved views, checked against a corpus rather than by reading them."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from bounty_searcher.domain.models import TriageStatus
from bounty_searcher.store import bounties as store_bounties
from bounty_searcher.store import triage, views
from bounty_searcher.store.bounties import SortKey
from bounty_searcher.store.db import Database
from tests.store.corpus import NOW, bounty, fill


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with Database(tmp_path / "state.db") as db:
        yield db.conn


def read(conn: sqlite3.Connection, view: views.View) -> list[str]:
    page = store_bounties.list_bounties(
        conn, as_of=NOW, filters=view.filters, sort=view.sort
    )
    return [row.bounty.key for row in page.rows]


def test_every_name_builds() -> None:
    for name in views.ViewName:
        view = views.build(name)
        assert view.name is name
        assert view.title
        assert view.description


def test_tonight_hides_decided_claimed_and_suspect(conn: sqlite3.Connection) -> None:
    ids = fill(
        conn,
        [
            bounty(1),
            bounty(2),
            bounty(3, claim_reason="assigned to someone"),
            bounty(4, stars=0),
        ],
    )
    triage.set_status(conn, [ids[1]], TriageStatus.DISMISSED, NOW)

    assert read(conn, views.build(views.ViewName.TONIGHT)) == ["owner/repo#1"]


def test_tonight_brings_back_a_snooze_once_it_expires(conn: sqlite3.Connection) -> None:
    ids = fill(conn, [bounty(1)])
    triage.set_status(
        conn,
        list(ids),
        TriageStatus.SNOOZED,
        NOW,
        snooze_until=NOW + timedelta(days=1),
    )
    filters = views.build(views.ViewName.TONIGHT).filters

    assert store_bounties.list_bounties(conn, as_of=NOW, filters=filters).total == 0
    assert (
        store_bounties.list_bounties(
            conn, as_of=NOW + timedelta(days=2), filters=filters
        ).total
        == 1
    )


def test_payday_orders_by_money(conn: sqlite3.Connection) -> None:
    fill(conn, [bounty(1), bounty(2), bounty(3)])
    view = views.build(views.ViewName.PAYDAY)

    assert view.sort is SortKey.PAYOUT
    assert read(conn, view) == ["owner/repo#3", "owner/repo#2", "owner/repo#1"]


def test_changed_is_empty_until_a_scan_has_completed(conn: sqlite3.Connection) -> None:
    fill(conn, [bounty(1), bounty(2)])

    assert read(conn, views.build(views.ViewName.CHANGED)) == []


def test_changed_finds_what_moved_and_not_what_arrived(
    conn: sqlite3.Connection,
) -> None:
    fill(conn, [bounty(1, title="Before"), bounty(2)])

    second = NOW + timedelta(days=1)
    fill(conn, [bounty(1, title="After"), bounty(3)], second)

    view = views.build(views.ViewName.CHANGED, last_scan_started=second)
    assert read(conn, view) == ["owner/repo#1"]


def test_changed_ignores_a_sweep_that_only_looked(conn: sqlite3.Connection) -> None:
    """Seeing the same bounty again is not a change, so nothing shows."""
    fill(conn, [bounty(1)])

    second = NOW + timedelta(days=1)
    fill(conn, [bounty(1)], second)

    view = views.build(views.ViewName.CHANGED, last_scan_started=second)
    assert read(conn, view) == []


def test_all_hides_nothing(conn: sqlite3.Connection) -> None:
    fill(conn, [bounty(1), bounty(2, claim_reason="pr open"), bounty(3, stars=0)])

    assert len(read(conn, views.build(views.ViewName.ALL))) == 3
