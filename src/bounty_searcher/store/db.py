"""Connections, pragmas, and the migration runner.

One connection is opened per process and reused. SQLite is not the bottleneck
here as long as it is configured properly, so it is configured properly once,
in this module, and nowhere else.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from types import TracebackType

MIGRATIONS = "bounty_searcher.store.migrations"

_MIGRATION_NAME = re.compile(r"^(\d{3})_([a-z0-9_]+)\.sql$")

PRAGMAS = (
    # Readers never block the scan writer, which is what lets triage carry on
    # while a sweep is running.
    "PRAGMA journal_mode = WAL",
    # Durable enough: WAL plus NORMAL loses at most the last transaction on a
    # power cut, and the corpus is rebuildable anyway.
    "PRAGMA synchronous = NORMAL",
    "PRAGMA foreign_keys = ON",
    # 256 MB of memory-mapped reads. The corpus is read far more than written.
    "PRAGMA mmap_size = 268435456",
    "PRAGMA busy_timeout = 5000",
)

SCHEMA_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migration (
    version    INTEGER PRIMARY KEY,
    name       TEXT    NOT NULL,
    applied_at INTEGER NOT NULL
)
"""


def default_db_path() -> Path:
    return Path.home() / ".bounty-searcher" / "state.db"


def to_ts(value: datetime) -> int:
    """Whole seconds since the epoch. Every timestamp column holds one."""
    return int(value.timestamp())


def from_ts(value: int) -> datetime:
    return datetime.fromtimestamp(value, UTC)


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open a configured connection, creating the parent directory if needed."""
    resolved = Path(path) if path else default_db_path()
    if resolved != Path(":memory:"):
        resolved.parent.mkdir(parents=True, exist_ok=True)

    # The connection outlives the thread that opened it: an ASGI server runs
    # the event loop wherever it likes, and everything that touches the corpus
    # is serialised onto that loop rather than by a lock here. SQLite's own
    # default threading mode is serialised, so the handle is safe to share.
    conn = sqlite3.connect(resolved, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    for pragma in PRAGMAS:
        conn.execute(pragma)
    return conn


def _migration_files() -> list[tuple[int, str, str]]:
    """Every migration as (version, name, sql), in order."""
    found = []
    for entry in resources.files(MIGRATIONS).iterdir():
        match = _MIGRATION_NAME.match(entry.name)
        if match:
            found.append(
                (int(match.group(1)), match.group(2), entry.read_text("utf-8"))
            )
    return sorted(found)


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply every migration this database has not seen. Returns their names.

    Forward only. Migrations are applied one file at a time and recorded as
    they land, and every statement in them is idempotent, so a run interrupted
    part way through a file is repaired by running it again.
    """
    conn.execute(SCHEMA_TABLE)
    applied = {
        row["version"] for row in conn.execute("SELECT version FROM schema_migration")
    }

    landed = []
    for version, name, sql in _migration_files():
        if version in applied:
            continue
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO schema_migration (version, name, applied_at) VALUES (?, ?, ?)",
            (version, name, to_ts(datetime.now(UTC))),
        )
        landed.append(name)
    return landed


class Database:
    """An open, migrated database. Hold one, pass it around, close it once."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else default_db_path()
        self.conn = connect(self.path)
        migrate(self.conn)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
