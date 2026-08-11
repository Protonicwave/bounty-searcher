"""Bounties that exist only as a comment.

Algora, Polar and the rest do not edit the issue when money is attached to it.
They post a comment. Issue search does not index comments, so none of these
bounties can be found by any phrasing of any search query, which is the single
largest hole in the coverage of a search-only crawler.

Reading them directly closes it. Listing a repository's issue comments is one
core request per hundred comments and supports both ``since`` and conditional
requests, so on a watchlist it is close to free.

This replaces talking to the platforms themselves. Their public APIs are no
longer there to talk to: Polar's issue funding endpoints have been withdrawn,
and Algora's bounty listing no longer serves anything outside its own front
end. The comment is what remains, and it is on GitHub, where a token we
already hold can read it.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime

from ...domain.models import Amount, Bounty
from ...domain.parse import extract_comment_amount
from ..base import SourceQuery, SourceResult
from .client import GitHubClient, GitHubError
from .issues import JsonDict, issue_to_bounty

log = logging.getLogger(__name__)

NAME = "github-comments"

RESULTS_PER_PAGE = 100
MAX_PAGES = 3
# Each candidate costs a request to resolve into an issue. A repository that
# produces more than this in one sweep is either enormous or is something
# other than what we are looking for.
MAX_CANDIDATES = 25

# Accounts that post a bounty comment because money has actually been escrowed.
BOUNTY_BOTS = frozenset(
    {
        "algora-pbc[bot]",
        "algora[bot]",
        "polar-sh[bot]",
        "polarsource[bot]",
        "gitcoinbot",
        "bountysource[bot]",
    }
)

# Phrases that mean the comment is attaching money rather than discussing it.
# A bot list alone goes stale the moment a platform renames its account.
BOUNTY_MARKERS = (
    "/bounty",
    "algora.io/bounties",
    "polar.sh",
    "bounty has been posted",
    "has been rewarded",
)


def _issue_number(comment: JsonDict) -> int | None:
    """The issue a comment hangs off, read from its API url."""
    url = comment.get("issue_url", "")
    try:
        return int(url.rstrip("/").rsplit("/", 1)[-1])
    except ValueError:
        return None


def comment_amount(comment: JsonDict) -> Amount | None:
    """The payout a comment attaches, or None if it is not attaching one."""
    author = (comment.get("user") or {}).get("login", "")
    body = comment.get("body") or ""
    trusted = author in BOUNTY_BOTS

    if not trusted and not any(marker in body.lower() for marker in BOUNTY_MARKERS):
        # Somebody saying they would pay fifty dollars is not a bounty.
        return None

    return extract_comment_amount(body, trusted=trusted)


class CommentSource:
    """Repository comments, read for the bounties nothing else can see."""

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
        return tuple(SourceQuery(NAME, repo, cost=2) for repo in self._repos)

    async def fetch(self, query: SourceQuery) -> SourceResult:
        repo = query.query
        try:
            candidates, requests = await self._candidates(repo)
        except GitHubError as exc:
            log.warning("comments failed for %s (%s)", repo, exc)
            return SourceResult(query, (), 0, error=str(exc))

        found: list[Bounty] = []
        for number, amount in list(candidates.items())[:MAX_CANDIDATES]:
            try:
                item: JsonDict = await self._client.get_json(
                    f"/repos/{repo}/issues/{number}"
                )
            except GitHubError as exc:
                log.debug("issue %s#%s failed: %s", repo, number, exc)
                continue
            requests += 1
            bounty = issue_to_bounty(
                item, source=f"{NAME}:{repo}", repo=repo, amount=amount
            )
            if bounty is not None and bounty.state == "open":
                found.append(bounty)

        if len(candidates) > MAX_CANDIDATES:
            log.warning(
                "%s: %d comment bounties found, %d resolved this sweep",
                repo,
                len(candidates),
                MAX_CANDIDATES,
            )

        return SourceResult(query, tuple(found), requests)

    async def _candidates(self, repo: str) -> tuple[dict[int, Amount], int]:
        """Issue numbers with money attached in a comment, best figure each."""
        candidates: dict[int, Amount] = {}
        requests = 0

        params: dict[str, object] = {
            "sort": "updated",
            "direction": "desc",
            "per_page": RESULTS_PER_PAGE,
        }
        if self._since is not None:
            params["since"] = self._since.isoformat().replace("+00:00", "Z")

        for page in range(1, MAX_PAGES + 1):
            comments: list[JsonDict] | None = await self._client.get_json(
                f"/repos/{repo}/issues/comments",
                {**params, "page": page},
                conditional=True,
            )
            requests += 1
            if comments is None:
                break

            for comment in comments:
                amount = comment_amount(comment)
                number = _issue_number(comment)
                if amount is None or number is None:
                    continue
                # A thread can raise its bounty over several comments. The
                # figure that pays is the largest.
                best = candidates.get(number)
                if best is None or amount.minor_units > best.minor_units:
                    candidates[number] = amount

            if len(comments) < RESULTS_PER_PAGE:
                break

        return candidates, requests
