"""Assembling the sources one sweep will run.

Which sources a sweep uses is a property of the settings and the corpus, not of
whoever asked for the sweep, so it is decided here and both the command line
and the API get the same answer.
"""

from __future__ import annotations

from ..config import ScanSettings
from ..sources.base import Source
from ..sources.github.client import GitHubClient
from ..sources.github.comments import CommentSource
from ..sources.github.repos import WatchlistSource
from ..sources.github.search import SearchSource
from ..store import repos as store_repos
from ..store import scans
from ..store.db import Database
from .planner import Planner


def build_sources(
    client: GitHubClient, db: Database, settings: ScanSettings, planner: Planner
) -> tuple[list[Source], int]:
    """Every source a sweep will run, and how many requests it expects to cost."""
    planned = planner.plan()
    sources: list[Source] = [
        SearchSource(client, [query.as_source_query() for query in planned])
    ]
    cost = sum(query.pages for query in planned)

    previous = scans.latest_run(db.conn)
    since = (
        previous.finished_at
        if previous is not None and previous.status is scans.RunStatus.DONE
        else None
    )

    watched = store_repos.watchlist(db.conn, settings.watchlist)
    if watched:
        sources.append(WatchlistSource(client, watched, since=since))
        cost += len(watched)
        if settings.watch_comments:
            sources.append(CommentSource(client, watched, since=since))
            cost += 2 * len(watched)

    return sources, cost
