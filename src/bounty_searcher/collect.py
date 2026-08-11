"""Turning GitHub search results into scored Bounty objects.

The search step is deliberately broad -- a dozen overlapping queries, then
dedupe -- because there is no single label or convention that catches even
half of the bounties on GitHub. Precision comes from `parse.looks_like_bounty`
and the scorer, not from the queries.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from .github import GitHub, GitHubError, JsonDict, parse_ts
from .models import Bounty
from .parse import extract_amount, looks_like_bounty
from .store import Store

log = logging.getLogger(__name__)

# Each entry is an issue-search query fragment; `state:open type:issue` and any
# language filter get appended automatically.
QUERY_TEMPLATES = [
    "label:bounty",
    "label:bountied",
    'label:"has bounty"',
    'label:"💰 bounty"',
    'label:"bounty 💵"',
    'label:"paid bounty"',
    'label:"bounty available"',
    'label:"$"',
    '"bounty" in:title',
    '"/bounty" in:body',
    '"algora.io/bounties" in:body',
    '"polar.sh" in:body label:bug',
]


def build_queries(
    languages: list[str] | None = None,
    extra_qualifiers: str = "",
    templates: list[str] | None = None,
) -> list[str]:
    """Cross the query templates with the languages you care about."""
    base = templates or QUERY_TEMPLATES
    langs = languages or []
    queries = []

    for template in base:
        parts = [template, "state:open", "type:issue"]
        if extra_qualifiers:
            parts.append(extra_qualifiers)

        if langs:
            for lang in langs:
                queries.append(" ".join(parts + [f"language:{lang}"]))
        else:
            queries.append(" ".join(parts))

    return queries


def _repo_from_url(repository_url: str) -> str:
    # https://api.github.com/repos/owner/name -> owner/name
    return "/".join(repository_url.rstrip("/").split("/")[-2:])


def item_to_bounty(item: JsonDict, source: str) -> Bounty | None:
    """Convert one search result. Returns None if it isn't really a bounty."""
    if "pull_request" in item:
        return None  # search sometimes leaks PRs despite type:issue

    labels = [label["name"] for label in item.get("labels", [])]
    title = item.get("title", "")
    body = item.get("body") or ""

    if not looks_like_bounty(labels, title, body):
        return None

    amount, currency, amount_source = extract_amount(labels, title, body)
    assignee = (item.get("assignee") or {}).get("login")

    return Bounty(
        source=source,
        repo=_repo_from_url(item["repository_url"]),
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
        amount=amount,
        currency=currency,
        amount_source=amount_source,
        claimed=bool(assignee),
        claim_reason=f"assigned to @{assignee}" if assignee else "",
    )


# (index, total, query, kept) -- enough for a caller to draw a progress line.
type ProgressHook = Callable[[int, int, str, int], None]


def collect(
    gh: GitHub,
    queries: list[str],
    max_per_query: int = 100,
    on_progress: ProgressHook | None = None,
) -> list[Bounty]:
    """Run every query, dedupe by repo#number, keep the richest record."""
    found: dict[str, Bounty] = {}

    for i, query in enumerate(queries, 1):
        try:
            items = gh.search_issues(query, max_results=max_per_query)
        except GitHubError as exc:
            log.warning("skipping query %r: %s", query, exc)
            continue

        kept = 0
        for item in items:
            bounty = item_to_bounty(item, source=query)
            if bounty is None:
                continue
            existing = found.get(bounty.key)
            # Prefer whichever record actually managed to parse an amount.
            if existing is None or (existing.amount is None and bounty.amount):
                found[bounty.key] = bounty
                kept += 1

        if on_progress:
            on_progress(i, len(queries), query, kept)

    return list(found.values())


def enrich_repos(gh: GitHub, bounties: list[Bounty], store: Store) -> None:
    """Attach language and star count, using the on-disk cache where possible.

    Search results don't include repo metadata, so this is one API call per
    unique repo -- cached for a week since language and rough star count don't
    move fast enough to matter for scoring.
    """
    repos = {b.repo for b in bounties}
    meta: dict[str, JsonDict] = {}

    for name in repos:
        cached = store.get_repo(name)
        if cached is not None:
            meta[name] = cached
            continue
        try:
            data = gh.get_repo(name)
        except GitHubError as exc:
            log.debug("repo lookup failed for %s: %s", name, exc)
            continue
        record = {
            "language": data.get("language"),
            "stars": data.get("stargazers_count"),
            "archived": data.get("archived", False),
            "fork": data.get("fork", False),
        }
        store.put_repo(name, record)
        meta[name] = record

    for b in bounties:
        info = meta.get(b.repo)
        if info:
            b.language = info.get("language")
            b.stars = info.get("stars")
            b.is_fork = info.get("fork", False)
            if info.get("archived"):
                b.claimed = True
                b.claim_reason = "repo archived"


def detect_claims(gh: GitHub, bounties: list[Bounty]) -> None:
    """Deep check: has someone already opened a PR or called dibs?

    Two API calls per issue, so callers should only run this on the shortlist
    they're actually considering working on.
    """
    dibs_markers = ("/attempt", "i'll take this", "working on this", "i am working on")

    for b in bounties:
        if b.claimed:
            continue
        try:
            events = gh.issue_timeline(b.repo, b.number)
        except GitHubError as exc:
            log.debug("timeline failed for %s: %s", b.key, exc)
            continue

        for event in events:
            if event.get("event") == "cross-referenced":
                issue = event.get("source", {}).get("issue", {})
                if "pull_request" in issue and issue.get("state") == "open":
                    b.claimed = True
                    b.claim_reason = f"open PR #{issue.get('number')} references it"
                    break

        if b.claimed:
            continue

        try:
            comments = gh.issue_comments(b.repo, b.number)
        except GitHubError:
            continue

        for comment in comments:
            text = (comment.get("body") or "").lower()
            if any(marker in text for marker in dibs_markers):
                author = (comment.get("user") or {}).get("login", "someone")
                b.claimed = True
                b.claim_reason = f"@{author} claimed it in a comment"
                break
