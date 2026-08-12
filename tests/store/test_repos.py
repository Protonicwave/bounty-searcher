"""The repository cache, and the watchlist derived from the corpus."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from bounty_searcher.domain.models import Repository, TriageStatus
from bounty_searcher.store import repos, triage
from bounty_searcher.store.db import Database
from tests.store.corpus import NOW, bounty, fill


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with Database(tmp_path / "state.db") as db:
        yield db.conn


def test_facts_survive_a_round_trip(conn: sqlite3.Connection) -> None:
    repos.put_meta(
        conn,
        [Repository("owner/name", "Rust", 4_200, archived=True, is_fork=False)],
        NOW,
    )

    stored = repos.get_meta(conn, ["owner/name"], NOW)["owner/name"]

    assert stored == Repository("owner/name", "Rust", 4_200, archived=True)


def test_a_stale_entry_is_not_offered(conn: sqlite3.Connection) -> None:
    repos.put_meta(conn, [Repository("owner/name", "Rust", 10)], NOW)

    later = NOW + repos.REPO_META_TTL + timedelta(seconds=1)

    assert repos.get_meta(conn, ["owner/name"], later) == {}


def test_asking_about_nothing_costs_no_query(conn: sqlite3.Connection) -> None:
    assert repos.get_meta(conn, [], NOW) == {}


def test_re_fetching_replaces_what_was_there(conn: sqlite3.Connection) -> None:
    repos.put_meta(conn, [Repository("owner/name", "Rust", 10)], NOW)
    repos.put_meta(conn, [Repository("owner/name", "Go", 20)], NOW)

    stored = repos.get_meta(conn, ["owner/name"], NOW)["owner/name"]

    assert (stored.language, stored.stars) == ("Go", 20)


def test_a_repository_that_has_paid_is_worth_watching(conn: sqlite3.Connection) -> None:
    fill(conn, [bounty(1, repo="pays/well")])

    assert repos.watchlist(conn) == ["pays/well"]


def test_a_repository_with_no_money_in_it_is_not(conn: sqlite3.Connection) -> None:
    fill(conn, [bounty(1, repo="quiet/repo", amount=None)])

    assert repos.watchlist(conn) == []


def test_a_suspect_payout_does_not_earn_a_place(conn: sqlite3.Connection) -> None:
    # A priced bounty from a repository nobody has starred is the spam
    # signature, and polling it every night would be quota spent on nothing.
    fill(conn, [bounty(1, repo="spam/farm", stars=0)])

    assert repos.watchlist(conn) == []


def test_shortlisting_puts_a_repository_on_the_list(conn: sqlite3.Connection) -> None:
    ids = fill(conn, [bounty(1, repo="spam/farm", stars=0)])
    triage.set_status(conn, [ids[0]], TriageStatus.SHORTLISTED, NOW)

    # Your judgement overrules the spam heuristic.
    assert repos.watchlist(conn) == ["spam/farm"]


def test_the_configured_seed_comes_first(conn: sqlite3.Connection) -> None:
    fill(conn, [bounty(1, repo="pays/well")])

    assert repos.watchlist(conn, seed=("hand/picked",)) == ["hand/picked", "pays/well"]


def test_a_seeded_repository_is_not_listed_twice(conn: sqlite3.Connection) -> None:
    fill(conn, [bounty(1, repo="pays/well")])

    assert repos.watchlist(conn, seed=("pays/well",)) == ["pays/well"]


def test_the_quietest_repositories_are_what_a_limit_trims(
    conn: sqlite3.Connection,
) -> None:
    fill(conn, [bounty(1, repo="old/repo")], now=NOW - timedelta(days=30))
    fill(conn, [bounty(2, repo="new/repo")], now=NOW)

    assert repos.watchlist(conn, limit=1) == ["new/repo"]
