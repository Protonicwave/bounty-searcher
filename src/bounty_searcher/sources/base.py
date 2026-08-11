"""What every source has to look like.

A source knows two things: which units of work it has, and how to turn one of
them into bounties. Everything else, concurrency, resumption, writing and
progress, belongs to the runner, so adding a source never means touching it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from ..domain.models import Bounty


@dataclass(frozen=True, slots=True)
class SourceQuery:
    """One unit of work: a search query, a repository name, a page cursor.

    ``params`` carries anything the source needs that is not expressible in
    ``query``, such as which direction to sort in. It is part of ``key``
    because two queries differing only in a parameter are two distinct pieces
    of work, and the scan bookkeeping keys on that.
    """

    source: str
    query: str
    cost: int = 1
    params: tuple[tuple[str, str], ...] = field(default=())

    @property
    def key(self) -> str:
        """Stable identity, as recorded against the run."""
        if not self.params:
            return self.query
        rendered = " ".join(f"{name}={value}" for name, value in self.params)
        return f"{self.query} [{rendered}]"

    def param(self, name: str, default: str) -> str:
        for key, value in self.params:
            if key == name:
                return value
        return default


@dataclass(frozen=True, slots=True)
class SourceResult:
    """What one query produced, and what it cost to find out.

    A source never raises for an expected failure. An unreachable platform or a
    repository that has been deleted comes back as an ``error``, which the
    runner records against the query and then carries on, because one dead
    query must not end a sweep.
    """

    query: SourceQuery
    bounties: tuple[Bounty, ...] = ()
    requests: int = 0
    # The query hit a ceiling imposed by the API rather than running out of
    # results, so there are more bounties behind it than it can return.
    saturated: bool = False
    error: str | None = None


class Source(Protocol):
    """A named producer of bounties."""

    name: str

    def plan(self) -> Sequence[SourceQuery]:
        """Every query this source intends to run, in the order it wants."""
        ...

    async def fetch(self, query: SourceQuery) -> SourceResult:
        """Run one query. Must not raise for a failure it can describe."""
        ...
