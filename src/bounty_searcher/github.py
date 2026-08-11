"""Thin GitHub REST client: search, repo metadata, and claim detection.

Only the pieces we need, with the two rate limits that actually bite:
the search endpoint (30 req/min authenticated) and the secondary abuse
limit that returns 403 with a Retry-After header.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime
from typing import Any

import requests

log = logging.getLogger(__name__)

API = "https://api.github.com"
UA = "bounty-searcher/0.1"

# One decoded JSON object from the API. Only the fields we read are ever
# touched, so there is nothing to gain from modelling the whole payload.
type JsonDict = dict[str, Any]


class RateLimited(RuntimeError):
    pass


class GitHubError(RuntimeError):
    pass


def parse_ts(value: str) -> datetime:
    """GitHub timestamps are RFC3339 with a literal Z."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


class GitHub:
    def __init__(self, token: str | None = None, max_retries: int = 4):
        self.token = token or os.environ.get("GITHUB_TOKEN") or ""
        self.max_retries = max_retries
        self.session = requests.Session()
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": UA,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        self.session.headers.update(headers)

    # -- transport ---------------------------------------------------------

    def _get(self, path: str, params: JsonDict | None = None) -> requests.Response:
        url = path if path.startswith("http") else f"{API}{path}"

        for attempt in range(self.max_retries):
            resp = self.session.get(url, params=params, timeout=30)

            if resp.status_code == 200:
                return resp

            if resp.status_code in (403, 429):
                wait = self._retry_delay(resp)
                if wait is not None and attempt < self.max_retries - 1:
                    log.warning("rate limited, sleeping %.0fs (%s)", wait, path)
                    time.sleep(wait)
                    continue
                # Search and core are separate buckets with very different
                # limits, so name the one that actually ran out.
                is_search = "/search/" in url
                if not self.token:
                    limits = (
                        "10 to 30 search requests/minute"
                        if is_search
                        else "60 to 5000 requests/hour"
                    )
                    hint = f"Set GITHUB_TOKEN to raise the ceiling from {limits}."
                else:
                    hint = (
                        "Try again shortly, or narrow your queries."
                        if is_search
                        else "Try again shortly, or scan fewer repos with "
                        "--max-per-query."
                    )
                bucket = "search" if is_search else "core"
                raise RateLimited(f"GitHub {bucket} rate limit hit. {hint}")

            if resp.status_code == 422:
                # Malformed search query -- skip it rather than kill the run.
                raise GitHubError(f"422 invalid query for {path}: {resp.text[:200]}")

            if 500 <= resp.status_code < 600 and attempt < self.max_retries - 1:
                time.sleep(2**attempt)
                continue

            raise GitHubError(f"{resp.status_code} from {path}: {resp.text[:200]}")

        raise GitHubError(f"gave up on {path} after {self.max_retries} attempts")

    @staticmethod
    def _retry_delay(resp: requests.Response) -> float | None:
        """Seconds to wait, or None if this 403 isn't a rate limit."""
        if (retry_after := resp.headers.get("Retry-After")) is not None:
            try:
                return min(float(retry_after), 120.0)
            except ValueError:
                return 60.0

        if resp.headers.get("X-RateLimit-Remaining") == "0":
            reset = resp.headers.get("X-RateLimit-Reset")
            if reset:
                try:
                    delta = float(reset) - time.time()
                except ValueError:
                    return 60.0
                return max(1.0, min(delta + 1, 120.0))
            return 60.0

        return None

    # -- endpoints ---------------------------------------------------------

    def search_issues(self, query: str, max_results: int = 200) -> list[JsonDict]:
        """Run one issue-search query, paging until exhausted or capped.

        The search API refuses to return more than 1000 results per query, so
        `max_results` above that is silently clamped by GitHub itself.
        """
        items: list[JsonDict] = []
        per_page = 100
        page = 1

        while len(items) < max_results:
            resp = self._get(
                "/search/issues",
                {
                    "q": query,
                    "per_page": per_page,
                    "page": page,
                    "sort": "created",
                    "order": "desc",
                },
            )
            data = resp.json()
            batch = data.get("items", [])
            items.extend(batch)

            if len(batch) < per_page or page * per_page >= min(
                data.get("total_count", 0), 1000
            ):
                break
            page += 1

        return items[:max_results]

    def get_repo(self, full_name: str) -> JsonDict:
        repo: JsonDict = self._get(f"/repos/{full_name}").json()
        return repo

    def issue_timeline(self, full_name: str, number: int) -> list[JsonDict]:
        """Timeline events -- used to spot a PR already opened against the issue."""
        events: list[JsonDict] = self._get(
            f"/repos/{full_name}/issues/{number}/timeline", {"per_page": 100}
        ).json()
        return events

    def issue_comments(self, full_name: str, number: int) -> list[JsonDict]:
        comments: list[JsonDict] = self._get(
            f"/repos/{full_name}/issues/{number}/comments", {"per_page": 100}
        ).json()
        return comments

    def rate_limit(self) -> JsonDict:
        limits: JsonDict = self._get("/rate_limit").json()
        return limits
