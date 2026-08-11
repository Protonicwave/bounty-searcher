from datetime import UTC, datetime
from pathlib import Path

from bounty_searcher.store.db import Database, connect, from_ts, migrate, to_ts


def test_pragmas_are_applied(tmp_path: Path) -> None:
    conn = connect(tmp_path / "state.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    conn.close()


def test_the_parent_directory_is_created(tmp_path: Path) -> None:
    conn = connect(tmp_path / "nested" / "deeper" / "state.db")
    conn.close()
    assert (tmp_path / "nested" / "deeper" / "state.db").is_file()


def test_migrations_run_once_and_in_order(tmp_path: Path) -> None:
    conn = connect(tmp_path / "state.db")
    first = migrate(conn)
    assert first == ["corpus", "cli_state"]
    assert migrate(conn) == []
    conn.close()


def test_every_table_the_corpus_needs_exists(tmp_path: Path) -> None:
    with Database(tmp_path / "state.db") as db:
        names = {
            row["name"]
            for row in db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert {
        "bounty",
        "bounty_score",
        "triage",
        "triage_journal",
        "scan_run",
        "scan_query",
        "bounty_fts",
    } <= names


def test_a_partly_applied_migration_is_repaired_by_rerunning(tmp_path: Path) -> None:
    """Every statement is idempotent, so an interrupted run just runs again."""
    conn = connect(tmp_path / "state.db")
    migrate(conn)
    conn.execute("DELETE FROM schema_migration")
    assert migrate(conn) == ["corpus", "cli_state"]
    conn.close()


def test_timestamps_round_trip_to_the_second() -> None:
    moment = datetime(2026, 6, 1, 12, 30, 45, tzinfo=UTC)
    assert from_ts(to_ts(moment)) == moment
