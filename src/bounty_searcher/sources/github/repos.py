"""Polling repositories directly, on the budget that can afford it.

Listing the open issues on a repository spends the core budget of 5,000 an
hour rather than the search budget of 30 a minute, which makes it roughly two
orders of magnitude cheaper per request. Conditional requests make it cheaper
still: a repository with nothing new comes back 304 and costs no quota at all.

So the watchlist is where the volume is. It also catches what search cannot,
because it does not depend on the maintainer having phrased anything the way
our vocabulary expects.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime

from ...domain.models import Bounty, Repository
from ...domain.parse import looks_like_bounty
from ..base import SourceQuery, SourceResult
from .client import GitHubClient, GitHubError, NotFound
from .issues import JsonDict, issue_to_bounty

log = logging.getLogger(__name__)

NAME = "github-watchlist"

RESULTS_PER_PAGE = 100
# A busy repository can have hundreds of open issues. Three pages of the most
# recently touched ones is the part worth having; the rest has been sitting
# there since the last sweep and was seen then.
MAX_PAGES = 3


async def fetch_repo(client: GitHubClient, name: str) -> Repository | None:
    """Language, stars and status for one repository. None if it is gone."""
    try:
        data: JsonDict = await client.get_json(f"/repos/{name}")
    except NotFound:
        return None
    except GitHubError as exc:
        log.debug("repository lookup failed for %s: %s", name, exc)
        return None

    return Repository(
        name=name,
        language=data.get("language"),
        stars=data.get("stargazers_count"),
        archived=bool(data.get("archived", False)),
        is_fork=bool(data.get("fork", False)),
    )


class WatchlistSource:
    """Open issues on repositories known to be worth watching."""

    name = NAME

    def __init__(
        self,
        client: GitHubClient,
        repos: Sequence[str],
        *,
        since: datetime | None = None,
    ) -> None:
        self._client = client
        self._repos = tuple(repos)
        self._since = since

    def plan(self) -> Sequence[SourceQuery]:
        return tuple(SourceQuery(NAME, repo) for repo in self._repos)

    async def fetch(self, query: SourceQuery) -> SourceResult:
        repo = query.query
        found: dict[str, Bounty] = {}
        requests = 0

        params: dict[str, object] = {
            "state": "open",
            "sort": "updated",
            "direction": "desc",
            "per_page": RESULTS_PER_PAGE,
        }
        if self._since is not None:
            # Only what has moved since the last sweep. Everything older was
            # read then.
            params["since"] = self._since.isoformat().replace("+00:00", "Z")

        for page in range(1, MAX_PAGES + 1):
            try:
                items: list[JsonDict] | None = await self._client.get_json(
                    f"/repos/{repo}/issues",
                    {**params, "page": page},
                    conditional=True,
                )
            except GitHubError as exc:
                log.warning("watchlist repository failed: %s (%s)", repo, exc)
                return SourceResult(
                    query, tuple(found.values()), requests, error=str(exc)
                )

            requests += 1
            if items is None:
                # Unchanged since last time, and free.
                break

            for item in items:
                if (bounty := self._to_bounty(item, repo)) is not None:
                    found[bounty.key] = bounty

            if len(items) < RESULTS_PER_PAGE:
                break

        return SourceResult(query, tuple(found.values()), requests)

    def _to_bounty(self, item: JsonDict, repo: str) -> Bounty | None:
        bounty = issue_to_bounty(item, source=f"{NAME}:{repo}", repo=repo)
        if bounty is None:
            return None
        if not looks_like_bounty(bounty.labels, bounty.title, bounty.body):
            return None
        return bounty
