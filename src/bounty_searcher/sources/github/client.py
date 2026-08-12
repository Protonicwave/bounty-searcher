"""Async transport for the GitHub API.

One client per sweep, shared by every worker. It owns the connection pool, the
retry policy and the conditional-request cache; it owns no opinion about what
is being fetched.

Retries are narrow on purpose. A 5xx or a dropped connection is worth trying
again, a rate limit is worth waiting out, and a 422 is a query GitHub will
refuse just as firmly the second time, so it is never retried.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable, Mapping
from types import TracebackType
from typing import Any
from urllib.parse import urlencode

import httpx

from .quota import Governor, Sleep

log = logging.getLogger(__name__)

API = "https://api.github.com"
USER_AGENT = "bounty-searcher"
API_VERSION = "2022-11-28"

# Long enough for a slow search, short enough that a hung connection does not
# hold a worker for the rest of the sweep.
DEFAULT_TIMEOUT = 30.0
DEFAULT_CONCURRENCY = 8
DEFAULT_RETRIES = 4

# A penalty GitHub asks for can be minutes. Anything beyond this is not worth
# holding a sweep open for, so the request fails and the query is recorded as
# failed rather than the run stalling.
MAX_PENALTY_SECONDS = 300.0

type Jitter = Callable[[], float]


class GitHubError(RuntimeError):
    """A request failed in a way the caller has to deal with."""


class NotFound(GitHubError):
    """The resource is gone: a deleted repository, a transferred issue."""


class RateLimited(GitHubError):
    """Out of budget, and waiting it out would take too long."""


class InvalidQuery(GitHubError):
    """GitHub rejected the query itself. Retrying changes nothing."""


def _cache_key(url: str, params: Mapping[str, Any] | None) -> str:
    if not params:
        return url
    return f"{url}?{urlencode(sorted(params.items()))}"


class GitHubClient:
    """Everything the sources use to reach GitHub.

    ``etags`` is a plain mapping of cache key to entity tag, handed in by the
    caller and read back afterwards. A conditional request that comes back 304
    costs no quota at all, which is what makes polling a watchlist every night
    affordable, but only if the tags outlive the process.
    """

    def __init__(
        self,
        token: str | None = None,
        *,
        governor: Governor | None = None,
        concurrency: int = DEFAULT_CONCURRENCY,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_RETRIES,
        etags: dict[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
        jitter: Jitter = random.random,
    ) -> None:
        self.governor = governor or Governor()
        self.etags: dict[str, str] = etags if etags is not None else {}
        self.max_retries = max_retries
        self._sleep = sleep
        self._jitter = jitter
        self._gate = asyncio.Semaphore(concurrency)

        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": USER_AGENT,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        self._http = httpx.AsyncClient(
            base_url=API,
            headers=headers,
            timeout=timeout,
            transport=transport,
            limits=httpx.Limits(max_connections=concurrency),
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> GitHubClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    # -- transport ---------------------------------------------------------

    async def get(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
        *,
        conditional: bool = False,
    ) -> httpx.Response:
        """Fetch a path, waiting for quota and retrying what is worth retrying.

        A conditional request may come back 304, which the caller is expected
        to read as "nothing has changed here" rather than as an error.
        """
        key = _cache_key(path, params)
        headers: dict[str, str] = {}
        if conditional and (etag := self.etags.get(key)):
            headers["If-None-Match"] = etag

        for attempt in range(self.max_retries):
            await self.governor.acquire(path)
            try:
                async with self._gate:
                    response = await self._http.get(
                        path, params=params, headers=headers
                    )
            except httpx.TransportError as exc:
                if attempt == self.max_retries - 1:
                    raise GitHubError(f"{path}: {exc}") from exc
                await self._back_off(attempt)
                continue

            self.governor.sync(path, response.headers)

            if response.status_code in (200, 304):
                if conditional and (tag := response.headers.get("ETag")):
                    self.etags[key] = tag
                return response

            if response.status_code in (403, 429):
                delay = self._penalty(response, attempt)
                if delay > MAX_PENALTY_SECONDS or attempt == self.max_retries - 1:
                    raise RateLimited(f"{path}: rate limited, {delay:.0f}s to wait")
                log.warning("rate limited on %s, pausing %.0fs", path, delay)
                self.governor.penalise(delay)
                continue

            if response.status_code == 404:
                raise NotFound(f"{path}: not found")

            if response.status_code == 422:
                raise InvalidQuery(f"{path}: {response.text[:200]}")

            if response.status_code >= 500 and attempt < self.max_retries - 1:
                await self._back_off(attempt)
                continue

            raise GitHubError(f"{path}: {response.status_code} {response.text[:200]}")

        raise GitHubError(f"{path}: gave up after {self.max_retries} attempts")

    async def get_json(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
        *,
        conditional: bool = False,
    ) -> Any:
        """As ``get``, but None when a conditional request finds no change."""
        response = await self.get(path, params, conditional=conditional)
        if response.status_code == 304:
            return None
        return response.json()

    def _penalty(self, response: httpx.Response, attempt: int) -> float:
        """How long to stop for, given what the response says.

        ``Retry-After`` is GitHub asking directly and is obeyed. Failing that,
        an exhausted budget says when it resets. A 403 that is neither is a
        secondary rate limit, which is undocumented and unmetered, so it gets
        exponential backoff with jitter like any other opaque refusal.
        """
        headers = {name.lower(): value for name, value in response.headers.items()}

        if (retry_after := headers.get("retry-after")) is not None:
            try:
                return float(retry_after)
            except ValueError:
                pass

        if headers.get("x-ratelimit-remaining") == "0":
            reset = headers.get("x-ratelimit-reset")
            try:
                if reset is not None:
                    return max(1.0, float(reset) - self.governor.now())
            except ValueError:
                pass

        return self._backoff_seconds(attempt)

    def _backoff_seconds(self, attempt: int) -> float:
        # Full jitter: spread the retries of concurrent workers out rather than
        # having all of them come back at the same instant.
        return (2.0**attempt) * (1.0 + self._jitter())

    async def _back_off(self, attempt: int) -> None:
        await self._sleep(self._backoff_seconds(attempt))
