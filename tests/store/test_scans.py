import sqlite3
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from bounty_searcher.store import scans
from bounty_searcher.store.db import Database
from tests.store.corpus import NOW


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with Database(tmp_path / "state.db") as db:
        yield db.conn


def test_a_run_starts_as_running(conn: sqlite3.Connection) -> None:
    run_id = scans.start_run(conn, NOW, planned_queries=12)
    run = scans.get_run(conn, run_id)

    assert run is not None
    assert run.status is scans.RunStatus.RUNNING
    assert run.planned_queries == 12
    assert run.started_at == NOW
    assert run.finished_at is None


def test_finishing_a_run_records_when_and_how(conn: sqlite3.Connection) -> None:
    run_id = scans.start_run(conn, NOW, planned_queries=1)
    done = NOW + timedelta(minutes=4)
    scans.finish_run(conn, run_id, done, scans.RunStatus.DONE)

    run = scans.get_run(conn, run_id)
    assert run is not None
    assert (run.status, run.finished_at, run.error) == (
        scans.RunStatus.DONE,
        done,
        None,
    )


def test_a_failed_run_keeps_its_reason(conn: sqlite3.Connection) -> None:
    run_id = scans.start_run(conn, NOW, planned_queries=1)
    scans.finish_run(conn, run_id, NOW, scans.RunStatus.FAILED, "token rejected")

    run = scans.get_run(conn, run_id)
    assert run is not None and run.error == "token rejected"


def test_query_yield_is_recorded_against_its_cost(conn: sqlite3.Connection) -> None:
    run_id = scans.start_run(conn, NOW, planned_queries=1)
    query_id = scans.start_query(conn, run_id, "github", "label:bounty", NOW)
    scans.finish_query(conn, query_id, NOW, results=100, new_bounties=7)

    row = conn.execute("SELECT * FROM scan_query WHERE id = ?", (query_id,)).fetchone()
    assert (row["results"], row["new_bounties"]) == (100, 7)
    assert row["status"] == scans.QueryStatus.DONE.value


def test_a_failed_query_is_not_counted_as_done(conn: sqlite3.Connection) -> None:
    run_id = scans.start_run(conn, NOW, planned_queries=1)
    query_id = scans.start_query(conn, run_id, "github", "label:bounty", NOW)
    scans.finish_query(conn, query_id, NOW, error="422 invalid query")

    assert scans.completed_queries(conn, run_id) == set()


def test_completed_queries_are_what_a_resumed_sweep_skips(
    conn: sqlite3.Connection,
) -> None:
    run_id = scans.start_run(conn, NOW, planned_queries=3)
    for query in ("label:bounty", "label:bountied"):
        query_id = scans.start_query(conn, run_id, "github", query, NOW)
        scans.finish_query(conn, query_id, NOW, results=10, new_bounties=2)
    scans.start_query(conn, run_id, "github", "label:paid", NOW)

    assert scans.completed_queries(conn, run_id) == {
        ("github", "label:bounty"),
        ("github", "label:bountied"),
    }


def test_the_same_query_from_two_sources_is_two_rows(conn: sqlite3.Connection) -> None:
    run_id = scans.start_run(conn, NOW, planned_queries=2)
    first = scans.start_query(conn, run_id, "github", "bounty", NOW)
    second = scans.start_query(conn, run_id, "algora", "bounty", NOW)
    assert first != second


def test_reclaiming_a_query_resets_it(conn: sqlite3.Connection) -> None:
    run_id = scans.start_run(conn, NOW, planned_queries=1)
    query_id = scans.start_query(conn, run_id, "github", "label:bounty", NOW)
    scans.finish_query(conn, query_id, NOW, error="timed out")

    again = scans.start_query(conn, run_id, "github", "label:bounty", NOW)
    row = conn.execute("SELECT * FROM scan_query WHERE id = ?", (again,)).fetchone()
    assert again == query_id
    assert (row["status"], row["error"]) == (scans.QueryStatus.RUNNING.value, None)


def test_an_unfinished_run_is_offered_for_resumption(conn: sqlite3.Connection) -> None:
    finished = scans.start_run(conn, NOW, planned_queries=1)
    scans.finish_run(conn, finished, NOW, scans.RunStatus.DONE)
    assert scans.resumable_run(conn) is None

    interrupted = scans.start_run(conn, NOW, planned_queries=1)
    resumable = scans.resumable_run(conn)
    assert resumable is not None and resumable.id == interrupted


def test_the_latest_run_is_what_the_status_line_reads(conn: sqlite3.Connection) -> None:
    scans.start_run(conn, NOW - timedelta(days=1), planned_queries=1)
    newest = scans.start_run(conn, NOW, planned_queries=1)

    latest = scans.latest_run(conn)
    assert latest is not None and latest.id == newest


def test_there_is_no_latest_run_before_the_first_scan(conn: sqlite3.Connection) -> None:
    assert scans.latest_run(conn) is None


def test_queries_go_when_their_run_does(conn: sqlite3.Connection) -> None:
    run_id = scans.start_run(conn, NOW, planned_queries=1)
    scans.start_query(conn, run_id, "github", "label:bounty", NOW)
    conn.execute("DELETE FROM scan_run WHERE id = ?", (run_id,))

    assert conn.execute("SELECT COUNT(*) FROM scan_query").fetchone()[0] == 0
