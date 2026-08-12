"""Helpers for building a corpus to read back."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from bounty_searcher.domain.models import Bounty
from bounty_searcher.domain.scoring import ScoreWeights
from bounty_searcher.store import bounties as store_bounties
from tests.domain.builders import amount

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
WEIGHTS = ScoreWeights(preferred_languages=("typescript",))


def bounty(number: int, **kwargs: Any) -> Bounty:
    defaults: dict[str, Any] = {
        "source": "test",
        "repo": "owner/repo",
        "number": number,
        "title": f"Fix thing {number}",
        "url": f"https://example.com/{number}",
        "created_at": NOW - timedelta(days=2),
        "updated_at": NOW - timedelta(days=1),
        "stars": 500,
        "language": "TypeScript",
        "amount": amount(100 * number),
    }
    defaults.update(kwargs)
    return Bounty(**defaults)


def fill(
    conn: sqlite3.Connection, items: list[Bounty], now: datetime = NOW
) -> tuple[int, ...]:
    """Write bounties and score them, the way a scan would."""
    result = store_bounties.upsert_many(conn, items, now)
    store_bounties.score_bounties(conn, WEIGHTS, now)
    return result.ids
