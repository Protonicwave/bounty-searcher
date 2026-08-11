"""Turning issue JSON into bounties, and spotting the ones already taken.

Both the search endpoint and the repository issue listings return the same
issue shape, so the conversion lives here once and both sources use it.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from ...domain.models import Amount, Bounty
from ...domain.parse import extract_amount
from .client import GitHubClient, GitHubError

log = logging.getLogger(__name__)

# One decoded JSON object from the API. Only the fields we read are ever
# touched, so there is nothing to gain from modelling the whole payload.
type JsonDict = dict[str, Any]

# Phrases people use to call dibs on an issue in a comment.
DIBS_MARKERS = ("/attempt", "i'll take this", "working on this", "i am working on")


def parse_ts(value: str) -> datetime:
    """GitHub timestamps are RFC3339 with a literal Z."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def repo_from_url(url: str) -> str:
    """``https://api.github.com/repos/owner/name`` to ``owner/name``."""
    return "/".join(url.rstrip("/").split("/")[-2:])


def issue_to_bounty(
    item: JsonDict,
    *,
    source: str,
    repo: str | None = None,
    amount: Amount | None = None,
) -> Bounty | None:
    """Convert one issue. None if it is really a pull request.

    ``amount`` overrides what the issue text says, for the sources that found
    the figure somewhere the issue itself does not carry, such as a bot
    comment.
    """
    if "pull_request" in item:
        # Search leaks pull requests despite type:issue, and the repository
        # issue listings return them by design.
        return None

    labels = tuple(label["name"] for label in item.get("labels", []))
    title = item.get("title", "")
    body = item.get("body") or ""
    assignee = (item.get("assignee") or {}).get("login")

    if repo is None:
        repo = repo_from_url(item["repository_url"])

    return Bounty(
        source=source,
        repo=repo,
        number=item["number"],
        title=title,
        url=item["html_url"],
        created_at=parse_ts(item["created_at"]),
        updated_at=parse_ts(item["updated_at"]),
        labels=labels,
        body=body,
        comments=item.get("comments", 0),
        assignee=assignee,
        state=item.get("state", "open"),
        amount=amount if amount is not None else extract_amount(labels, title, body),
        claim_reason=f"assigned to @{assignee}" if assignee else None,
    )


async def find_claim(client: GitHubClient, repo: str, number: int) -> str | None:
    """Why this issue is already spoken for, or None.

    Two requests per issue against the core budget, so this is for a shortlist
    you are actually considering, never for a whole sweep.
    """
    try:
        events: list[JsonDict] = await client.get_json(
            f"/repos/{repo}/issues/{number}/timeline", {"per_page": 100}
        )
    except GitHubError as exc:
        log.debug("timeline failed for %s#%s: %s", repo, number, exc)
        events = []

    for event in events:
        if event.get("event") != "cross-referenced":
            continue
        issue = event.get("source", {}).get("issue", {})
        if "pull_request" in issue and issue.get("state") == "open":
            return f"open PR #{issue.get('number')} references it"

    try:
        comments: list[JsonDict] = await client.get_json(
            f"/repos/{repo}/issues/{number}/comments", {"per_page": 100}
        )
    except GitHubError as exc:
        log.debug("comments failed for %s#%s: %s", repo, number, exc)
        return None

    for comment in comments:
        text = (comment.get("body") or "").lower()
        if any(marker in text for marker in DIBS_MARKERS):
            author = (comment.get("user") or {}).get("login", "someone")
            return f"@{author} claimed it in a comment"

    return None
