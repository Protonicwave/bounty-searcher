"""Plain constructors for domain tests.

Not fixtures. The domain is pure, so a test only ever needs a value and a
moment to score it against, both written out in full.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from bounty_searcher.domain.models import (
    Amount,
    AmountField,
    Bounty,
    Confidence,
    Provenance,
)

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def amount(units: float, currency: str = "USD") -> Amount:
    return Amount.from_units(
        Decimal(str(units)),
        currency,
        Confidence.HIGH,
        Provenance(AmountField.LABEL, "symbol", 0, 0, f"${units}"),
    )


def bounty(**kwargs: Any) -> Bounty:
    """A plausible bounty, two days old and last touched yesterday."""
    defaults: dict[str, Any] = {
        "source": "test",
        "repo": "owner/repo",
        "number": 1,
        "title": "Fix a thing",
        "url": "https://example.com",
        "created_at": datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 5, 31, 12, 0, tzinfo=UTC),
        "stars": 500,
        "language": "TypeScript",
    }
    defaults.update(kwargs)
    return Bounty(**defaults)
