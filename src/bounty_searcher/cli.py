"""Command line entry point.

The shape of a run is: sweep into the corpus, then read back out of it. The two
halves are independent, which is the point. A scan can be skipped entirely and
the same query answered from what is already stored, at no quota cost and in
milliseconds.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from .config import (
    ConfigError,
    ScanSettings,
    load_config,
    scan_settings,
    score_weights,
)
from .domain.models import MINOR_UNIT_EXPONENT, ScoredBounty
from .domain.scoring import ScoreWeights
from .domain.select import cap_per_repo
from .render import (
    _make_console,
    describe_dropped,
    render_explain,
    render_json,
    render_table,
)
from .scan.planner import Planner
from .scan.runner import ScanOutcome, ScanProgress, run_scan
from .scan.sources import build_sources
from .sources.github.client import GitHubClient, RateLimited
from .sources.github.issues import find_claim
from .store import bounties as store_bounties
from .store.bounties import BountyFilter, SortKey
from .store.db import Database, default_db_path
from .store.http_cache import load_etags, save_etags

console = _make_console(stderr=True)

# How much of the ranked corpus to read before the per-repo cap is applied.
# The cap needs more rows than it will show, since it discards some, but not
# the whole corpus.
WINDOW_MULTIPLIER = 5
MIN_WINDOW = 200


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bounty-searcher",
        description="Find paid GitHub issues you can actually win.",
    )
    p.add_argument(
        "--lang",
        action="append",
        default=None,
        metavar="LANG",
        help="language to search and to favour when scoring (repeatable)",
    )
    p.add_argument(
        "--min-amount",
        type=float,
        default=None,
        metavar="N",
        help="hide bounties paying less than N (unpriced ones are kept)",
    )
    p.add_argument(
        "--min-score",
        type=float,
        default=0.0,
        metavar="N",
        help="hide bounties scoring below N",
    )
    p.add_argument(
        "--limit", type=int, default=40, help="max rows to show (default 40)"
    )
    p.add_argument(
        "--budget",
        type=int,
        default=None,
        metavar="N",
        help="requests one sweep may spend (0 for no limit)",
    )
    p.add_argument(
        "--new-only",
        action="store_true",
        help="only show bounties this scan added to the corpus",
    )
    p.add_argument(
        "--include-claimed",
        action="store_true",
        help="keep issues that already have an assignee or a PR",
    )
    p.add_argument(
        "--include-suspect",
        action="store_true",
        help="keep payouts flagged as probably fake (spam repos)",
    )
    p.add_argument(
        "--min-stars",
        type=int,
        default=None,
        metavar="N",
        help="hide bounties from repos with fewer than N stars",
    )
    p.add_argument(
        "--per-repo",
        type=int,
        default=None,
        metavar="N",
        help="show at most N bounties per repo, best first (default 3; 0 disables)",
    )
    p.add_argument(
        "--deep",
        type=int,
        nargs="?",
        const=15,
        default=0,
        metavar="N",
        help="check the top N results for existing PRs and dibs comments "
        "(2 extra API calls each; default 15)",
    )
    p.add_argument("--explain", action="store_true", help="show the score breakdown")
    p.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    p.add_argument("--config", default=None, help="path to a config.toml")
    p.add_argument("--db", default=None, help=f"corpus (default {default_db_path()})")
    p.add_argument(
        "--no-scan",
        action="store_true",
        help="read the stored corpus without going near the network",
    )
    p.add_argument("--forget", action="store_true", help="empty the corpus and exit")
    p.add_argument("--token", default=None, help="GitHub token (or set GITHUB_TOKEN)")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def filters_from(
    args: argparse.Namespace, config: dict[str, Any], since: datetime | None
) -> BountyFilter:
    """The display filters, from flags first and the search table second."""
    search = config.get("search") or {}
    min_amount = (
        args.min_amount if args.min_amount is not None else search.get("min_amount")
    )
    min_stars = (
        args.min_stars if args.min_stars is not None else search.get("min_stars")
    )

    return BountyFilter(
        min_amount_minor=(
            None
            if min_amount is None
            else int(round(float(min_amount) * 10**MINOR_UNIT_EXPONENT))
        ),
        min_stars=min_stars,
        min_score=args.min_score or None,
        first_seen_after=since if args.new_only else None,
        include_suspect=args.include_suspect,
        include_claimed=args.include_claimed,
        # An unpriced bounty cannot fail an amount floor: the figure is often
        # negotiated in the thread, so those stay visible.
        include_unpriced=True,
    )


def read_corpus(
    db: Database, now: datetime, filters: BountyFilter, per_repo: int, limit: int
) -> tuple[list[ScoredBounty], dict[str, int], int]:
    """The ranked page to show, what the per-repo cap collapsed, and the total.

    Reads a window rather than the corpus: the cap discards rows, so it needs
    more than it will show, but nothing like all of them.
    """
    window = max(limit * WINDOW_MULTIPLIER, MIN_WINDOW)
    page = store_bounties.list_bounties(
        db.conn, as_of=now, filters=filters, sort=SortKey.SCORE, limit=window
    )
    kept, dropped = cap_per_repo(list(page.rows), per_repo)
    return kept[:limit], dropped, page.total


async def deep_check(
    client: GitHubClient,
    db: Database,
    weights: ScoreWeights,
    now: datetime,
    depth: int,
) -> int:
    """Look for an open PR or a dibs comment on the best unclaimed bounties.

    Two requests each, so it runs on a shortlist rather than on the corpus.
    """
    page = store_bounties.list_bounties(
        db.conn,
        as_of=now,
        filters=BountyFilter(include_claimed=False),
        sort=SortKey.SCORE,
        limit=depth,
    )

    claimed = 0
    for row in page.rows:
        reason = await find_claim(client, row.bounty.repo, row.bounty.number)
        if reason is None or reason == row.bounty.claim_reason or row.bounty_id is None:
            continue
        # Re-read for the body, so rewriting the row does not blank it.
        stored = store_bounties.get(db.conn, row.bounty_id)
        if stored is None:
            continue
        store_bounties.upsert_many(
            db.conn, [replace(stored.bounty, claim_reason=reason)], now
        )
        store_bounties.score_bounties(db.conn, weights, now, bounty_ids=[row.bounty_id])
        claimed += 1
    return claimed


async def sweep(
    db: Database,
    settings: ScanSettings,
    weights: ScoreWeights,
    now: datetime,
    token: str | None,
    depth: int,
) -> ScanOutcome:
    """One full pass: plan, fetch, write, and optionally deep check."""
    etags = load_etags(db.conn)
    planner = Planner(settings, now.date())

    def progress(event: ScanProgress) -> None:
        console.print(
            f"[dim][{event.completed}/{event.planned}][/] {event.query}"
            + (
                f" [red]{event.error}[/]"
                if event.error
                else f" [dim]-> {event.new_bounties} new[/]"
            )
        )

    async with GitHubClient(token, concurrency=settings.workers, etags=etags) as client:
        sources, cost = build_sources(client, db, settings, planner)
        console.print(f"[dim]planned {cost} requests across {len(sources)} sources[/]")

        outcome = await run_scan(
            db,
            client,
            sources,
            weights=weights,
            now=now,
            planner=planner,
            workers=settings.workers,
            on_progress=progress,
        )

        if depth:
            console.print(f"[dim]deep-checking the top {depth} for claims...[/]")
            claimed = await deep_check(client, db, weights, now, depth)
            if claimed:
                console.print(f"[dim]{claimed} turned out to be taken[/]")

        save_etags(db.conn, client.etags, now)

    return outcome


def report(outcome: ScanOutcome) -> None:
    resumed = " (resumed)" if outcome.resumed else ""
    console.print(
        f"[dim]{outcome.completed}/{outcome.planned} queries{resumed}, "
        f"{outcome.requests} requests, {outcome.inserted} new, "
        f"{outcome.changed} changed"
        + (f", {outcome.failed} failed" if outcome.failed else "")
        + "[/]"
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        console.print(f"[red]{exc}[/]")
        return 2

    languages = tuple(args.lang or ())
    settings = scan_settings(config, languages=languages)
    if args.budget is not None:
        settings = replace(settings, request_budget=args.budget)

    search = config.get("search") or {}
    per_repo = args.per_repo if args.per_repo is not None else search.get("per_repo", 3)
    weights = score_weights(config, settings.languages)

    # The clock is read once, here at the edge, and passed down. Everything
    # below scores and filters against this moment rather than its own.
    now = datetime.now(UTC)

    with Database(args.db) as db:
        if args.forget:
            console.print(f"Forgot {store_bounties.forget_all(db.conn)} bounties.")
            return 0

        if not args.no_scan:
            token = args.token or os.environ.get("GITHUB_TOKEN")
            if not token:
                console.print(
                    "[yellow]No GITHUB_TOKEN set.[/] Unauthenticated search is "
                    "limited to 10 requests/minute, so this run will be slow and "
                    "will not get far.\nCreate a token at "
                    "https://github.com/settings/tokens (no scopes needed for "
                    "public repos) and set GITHUB_TOKEN.\n"
                )
            try:
                report(asyncio.run(sweep(db, settings, weights, now, token, args.deep)))
            except RateLimited as exc:
                console.print(f"[red]{exc}[/]")
                return 1

        filters = filters_from(args, config, now)
        results, dropped, total = read_corpus(db, now, filters, per_repo, args.limit)
        new_keys = store_bounties.keys_first_seen_after(db.conn, now)

    if args.json:
        render_json(results, now, new_keys)
    elif not results:
        console.print(
            "[yellow]Nothing passed your filters.[/] "
            + (
                "This scan found nothing you had not already seen."
                if args.new_only
                else "Try lowering --min-score or --min-amount."
            )
        )
    else:
        render_table(results, now, new_keys, total=total)
        if note := describe_dropped(dropped, per_repo):
            console.print(f"[dim]{note}[/]")
        if args.explain:
            render_explain(results)

    return 0


if __name__ == "__main__":
    sys.exit(main())
