"""Serving the built interface beside the API.

The interface is a single page with no router, so the fallback is not about
client-side routes. It is about a reload, a bookmark and a typed URL landing on
the interface rather than on a 404 from a server the user never thinks about.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from bounty_searcher.api.app import create_app
from bounty_searcher.api.static import IMMUTABLE, REVALIDATE
from bounty_searcher.store.db import Database
from tests.store.corpus import NOW, WEIGHTS

ENTRY = "<!doctype html><title>bounty-searcher</title>"
ASSET = "export const hello = 1\n"


@pytest.fixture
def built(tmp_path: Path) -> Path:
    """A directory shaped the way the build leaves one."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    # newline="" so Windows does not rewrite the bytes the assertions compare.
    (dist / "index.html").write_text(ENTRY, encoding="utf-8", newline="")
    (dist / "assets" / "index-a1b2c3d4.js").write_text(
        ASSET, encoding="utf-8", newline=""
    )
    return dist


@pytest.fixture
async def client(tmp_path: Path, built: Path) -> AsyncIterator[httpx.AsyncClient]:
    with Database(tmp_path / "state.db") as db:
        app = create_app(db, weights=WEIGHTS, clock=lambda: NOW, interface=built)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://corpus"
        ) as opened:
            yield opened


async def test_the_root_serves_the_interface(client: httpx.AsyncClient) -> None:
    response = await client.get("/")

    assert response.status_code == 200
    assert response.text == ENTRY
    assert response.headers["content-type"].startswith("text/html")


async def test_the_entry_point_is_revalidated(client: httpx.AsyncClient) -> None:
    """Its name does not change between builds, so a stale copy would stick."""
    response = await client.get("/")

    assert response.headers["cache-control"] == REVALIDATE


async def test_a_hashed_asset_is_never_asked_about_again(
    client: httpx.AsyncClient,
) -> None:
    """The name carries the content hash, so the URL cannot change meaning."""
    response = await client.get("/assets/index-a1b2c3d4.js")

    assert response.status_code == 200
    assert response.text == ASSET
    assert response.headers["cache-control"] == IMMUTABLE


async def test_revalidating_the_entry_point_costs_no_body(
    client: httpx.AsyncClient,
) -> None:
    """What makes `no-cache` cheap: a reload sends a request and gets no bytes."""
    first = await client.get("/")

    again = await client.get("/", headers={"if-none-match": first.headers["etag"]})

    assert again.status_code == 304
    assert not again.content


async def test_an_unknown_path_falls_back_to_the_interface(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/bounties/12345")

    assert response.status_code == 200
    assert response.text == ENTRY


async def test_the_fallback_is_not_cached_as_that_path(
    client: httpx.AsyncClient,
) -> None:
    """It is the entry point wherever it is served from, so it revalidates."""
    response = await client.get("/some/deep/path")

    assert response.headers["cache-control"] == REVALIDATE


async def test_an_unknown_api_route_stays_a_404(client: httpx.AsyncClient) -> None:
    """A mistake against the API is worth seeing, not worth answering in HTML."""
    response = await client.get("/api/nothing-here")

    assert response.status_code == 404
    assert not response.headers["content-type"].startswith("text/html")


async def test_a_missing_asset_stays_a_404(client: httpx.AsyncClient) -> None:
    """A hashed name that is not on disk is a broken build, not a deep link.

    Falling back here would answer a script tag with HTML, and the browser
    would report a syntax error rather than the missing file it actually is.
    """
    response = await client.get("/assets/index-deadbeef.js")

    assert response.status_code == 404
    assert not response.headers["content-type"].startswith("text/html")


async def test_the_api_still_answers_underneath_it(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/bounties", params={"limit": 1})

    assert response.status_code == 200
    assert response.json()["total"] == 0


async def test_without_a_built_interface_the_api_is_still_whole(
    tmp_path: Path,
) -> None:
    """Development serves the interface from Vite, so there is nothing to mount."""
    with Database(tmp_path / "state.db") as db:
        app = create_app(db, weights=WEIGHTS, clock=lambda: NOW)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://corpus"
        ) as client:
            assert (await client.get("/api/meta")).status_code == 200
            assert (await client.get("/")).status_code == 404
