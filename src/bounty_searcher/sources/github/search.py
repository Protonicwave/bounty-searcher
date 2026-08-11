"""Issue search: broad queries, and the ceiling they run into.

This source runs whatever queries it is handed and reports whether each one
saturated. It does not decide what to ask; that is the planner's job, and
keeping the two apart is what lets the query strategy change without touching
any transport code.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from ...domain.models import Bounty
from ...domain.parse import looks_like_bounty
from ..base import SourceQuery, SourceResult
from .client import GitHubClient, GitHubError
from .issues import JsonDict, issue_to_bounty

log = logging.getLogger(__name__)

NAME = "github-search"

# GitHub returns 100 results a page and refuses to go past 1,000 for any one
# query, however many results it says there are.
RESULTS_PER_PAGE = 100
MAX_RESULTS_PER_QUERY = 1_000
MAX_PAGES = MAX_RESULTS_PER_QUERY // RESULTS_PER_PAGE


class SearchSource:
    """Issue search over the search budget."""

    name = NAME

    def __init__(self, client: GitHubClient, queries: Sequence[SourceQuery]) -> None:
        self._client = client
        self._queries = tuple(queries)

    def plan(self) -> Sequence[SourceQuery]:
        return self._queries

    async def fetch(self, query: SourceQuery) -> SourceResult:
        """Page through one query until it runs out or hits the ceiling."""
        found: dict[str, Bounty] = {}
        requests = 0
        saturated = False

        for page in range(1, MAX_PAGES + 1):
            try:
                payload = await self._client.get_json(
                    "/search/issues",
                    {
                        "q": query.query,
                        "per_page": RESULTS_PER_PAGE,
                        "page": page,
                        "sort": "created",
                        "order": query.param("order", "desc"),
                        # Legacy issue search is gone. Asking for it by name
                        # keeps the behaviour explicit rather than inherited.
                        "advanced_search": "true",
                    },
                )
            except GitHubError as exc:
                # One refused query must not end a sweep. Record why and let
                # the runner carry on with the rest of the plan.
                log.warning("query failed: %s (%s)", query.key, exc)
                return SourceResult(
                    query, tuple(found.values()), requests, error=str(exc)
                )

            requests += 1
            items: list[JsonDict] = payload.get("items", [])
            total = payload.get("total_count", 0)
            saturated = total > MAX_RESULTS_PER_QUERY

            for item in items:
                if (bounty := self._to_bounty(item, query)) is not None:
                    found[bounty.key] = bounty

            if len(items) < RESULTS_PER_PAGE:
                break
            if page * RESULTS_PER_PAGE >= min(total, MAX_RESULTS_PER_QUERY):
                break

        return SourceResult(query, tuple(found.values()), requests, saturated=saturated)

    def _to_bounty(self, item: JsonDict, query: SourceQuery) -> Bounty | None:
        bounty = issue_to_bounty(item, source=query.key)
        if bounty is None:
            return None
        # The queries are deliberately loose, so this is where precision comes
        # from: an issue that never mentions money is not a bounty.
        if not looks_like_bounty(bounty.labels, bounty.title, bounty.body):
            return None
        return bounty
