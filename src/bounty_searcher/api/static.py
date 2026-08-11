"""Serving the built interface from the same process as the API.

One origin, so there is no CORS to configure, nothing to keep in step between
two servers, and no port to remember beyond the one the launcher opens.

The two cache rules follow from how the build names things. Vite writes every
asset with a content hash in its file name, so a given asset URL can never
change what it returns and the browser need never ask about it again. The entry
point keeps its name across builds, so it has to be revalidated or a rebuild
would not be picked up until the cache expired.
"""

from __future__ import annotations

from pathlib import Path, PurePath

from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

ENTRY_POINT = "index.html"
# Where the build puts content-hashed files. Everything under it is immutable.
ASSETS = "assets"

IMMUTABLE = "public, max-age=31536000, immutable"
# Revalidate rather than never cache: the entry point still answers 304 from
# its etag, so the usual cost of a reload is a request and no body.
REVALIDATE = "no-cache"

# Sections that never fall back to the entry point. An unknown route under the
# API prefix is a mistake worth seeing, and a hashed asset that is not on disk
# is a broken build. Answering either with a page of HTML turns a clear failure
# into a confusing one: a script tag served HTML reports a syntax error rather
# than a missing file.
NO_FALLBACK = frozenset({"api", ASSETS})


def _section(path: str) -> str:
    """The first path segment, whatever separator the platform used.

    ``StaticFiles`` hands paths over with OS separators, so this cannot split
    on a forward slash and expect to work on Windows.
    """
    parts = PurePath(path).parts
    return parts[0] if parts else ""


def _cache_control(path: str) -> str:
    return IMMUTABLE if _section(path) == ASSETS else REVALIDATE


class Interface(StaticFiles):
    """The built interface, with its entry point as the fallback.

    Anything that is not a file on disk is served the entry point, so a reload
    or a bookmark on any path reaches the interface rather than a 404, except
    under the sections listed in `NO_FALLBACK`.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        # Starlette's own HTTPException, not FastAPI's subclass of it: this is
        # the one `StaticFiles` raises, and catching the narrower type would
        # never fire.
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or _section(path) in NO_FALLBACK:
                raise
            path = ENTRY_POINT
            response = await super().get_response(path, scope)

        response.headers["cache-control"] = _cache_control(path)
        return response


def interface_files(directory: Path) -> Interface:
    """The mount for a built interface. The caller checks it is there."""
    return Interface(directory=directory, html=True)
