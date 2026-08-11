"""The one large corpus the budget tests measure against.

Built once for the whole session, because filling fifty thousand rows costs far
more than any of the measurements taken over it. Every consumer opens its own
connection to the same file, so nothing is shared but the data.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from bounty_searcher.store import bounties as store_bounties
from bounty_searcher.store.db import Database
from tests.store.corpus import NOW, WEIGHTS, bounty

CORPUS_SIZE = 50_000


@pytest.fixture(scope="session")
def large_corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A filled, scored corpus of `CORPUS_SIZE` rows. Read it, do not write it."""
    path = tmp_path_factory.mktemp("corpus") / "state.db"
    with Database(path) as db:
        store_bounties.upsert_many(
            db.conn,
            [
                bounty(
                    n,
                    repo=f"owner{n % 700}/repo",
                    language=("Rust", "TypeScript", "Go", None)[n % 4],
                    stars=(n * 7) % 40_000,
                    comments=n % 30,
                    created_at=NOW - timedelta(days=n % 400),
                )
                for n in range(1, CORPUS_SIZE + 1)
            ],
            NOW,
        )
        store_bounties.score_bounties(db.conn, WEIGHTS, NOW)
    return path
