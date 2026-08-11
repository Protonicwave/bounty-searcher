"""Entity tags outliving the process that fetched them."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from bounty_searcher.store.db import Database
from bounty_searcher.store.http_cache import load_etags, save_etags
from tests.store.corpus import NOW


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with Database(tmp_path / "state.db") as db:
        yield db.conn


def test_nothing_stored_is_an_empty_cache(conn: sqlite3.Connection) -> None:
    assert load_etags(conn) == {}


def test_tags_survive_a_round_trip(conn: sqlite3.Connection) -> None:
    save_etags(conn, {"/repos/owner/name/issues": 'W/"abc"'}, NOW)

    assert load_etags(conn) == {"/repos/owner/name/issues": 'W/"abc"'}


def test_a_changed_tag_replaces_the_old_one(conn: sqlite3.Connection) -> None:
    save_etags(conn, {"/repos/owner/name": 'W/"one"'}, NOW)
    save_etags(conn, {"/repos/owner/name": 'W/"two"'}, NOW)

    assert load_etags(conn) == {"/repos/owner/name": 'W/"two"'}
