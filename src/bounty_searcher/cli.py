"""Command line entry point."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tomllib
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .collect import build_queries, collect, detect_claims, enrich_repos
from .domain.models import Bounty, ScoredBounty
from .domain.scoring import ScoreWeights
from .domain.select import cap_per_repo, rank
from .github import GitHub, RateLimited
from .render import (
    _make_console,
    describe_dropped,
    render_explain,
    render_json,
    render_table,
)
from .store.db import default_db_path
from .store.legacy import Store

console = _make_console(stderr=True)

CONFIG_LOCATIONS = [
    Path("config.toml"),
    Path.home() / ".bounty-searcher" / "config.toml",
]


def load_config(explicit: str | None = None) -> dict[str, Any]:
    paths = [Path(explicit)] if explicit else CONFIG_LOCATIONS
    for path in paths:
        if path.is_file():
            with path.open("rb") as fh:
                return tomllib.load(fh)
    if explicit:
        console.print(f"[red]config not found: {explicit}[/]")
        sys.exit(2)
    return {}


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
        "--max-per-query",
        type=int,
        default=100,
        help="results to pull per search query (default 100)",
    )
    p.add_argument(
        "--new-only",
        action="store_true",
        help="only show bounties not seen on a previous run",
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
    p.add_argument("--db", default=None, help=f"state db (default {default_db_path()})")
    p.add_argument(
        "--no-record", action="store_true", help="don't mark these results as seen"
    )
    p.add_argument(
        "--reset-seen", action="store_true", help="clear seen history and exit"
    )
    p.add_argument("--token", default=None, help="GitHub token (or set GITHUB_TOKEN)")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def weights_from(config: dict[str, Any], languages: list[str]) -> ScoreWeights:
    known = {f.name for f in fields(ScoreWeights)}
    overrides = {
        key: value
        for key, value in (config.get("scoring") or {}).items()
        if key in known
    }
    overrides["preferred_languages"] = tuple(languages)
    return ScoreWeights(**overrides)


def passes_filters(
    scored: ScoredBounty,
    args: argparse.Namespace,
    min_amount: float | None,
    min_stars: int | None,
) -> bool:
    b = scored.bounty
    if scored.score.total < args.min_score:
        return False
    if not args.include_claimed and b.claimed:
        return False
    if not args.include_suspect and scored.suspect:
        return False
    if min_stars is not None and (b.stars or 0) < min_stars:
        return False
    # An unpriced bounty can't fail an amount floor: the number is often
    # negotiated in the thread, so those stay visible.
    if min_amount is not None and b.amount is not None:
        return float(b.amount.units) >= min_amount
    return True


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    config = load_config(args.config)
    search_cfg = config.get("search") or {}

    languages = args.lang or search_cfg.get("languages") or []
    min_amount = (
        args.min_amount if args.min_amount is not None else search_cfg.get("min_amount")
    )
    extra_qualifiers = search_cfg.get("extra_qualifiers", "")
    min_stars = (
        args.min_stars if args.min_stars is not None else search_cfg.get("min_stars")
    )
    per_repo = (
        args.per_repo if args.per_repo is not None else search_cfg.get("per_repo", 3)
    )

    token = args.token or os.environ.get("GITHUB_TOKEN")
    if not token:
        console.print(
            "[yellow]No GITHUB_TOKEN set.[/] Unauthenticated search is limited to "
            "10 requests/minute, so this run will be slow and may hit the cap.\n"
            "Create a token at https://github.com/settings/tokens (no scopes needed "
            "for public repos) and set GITHUB_TOKEN.\n"
        )

    store = Store(args.db)

    if args.reset_seen:
        count = store.forget_all()
        store.close()
        console.print(f"Cleared {count} seen entries.")
        return 0

    gh = GitHub(token)
    queries = build_queries(languages, extra_qualifiers, search_cfg.get("queries"))

    def progress(i: int, total: int, query: str, kept: int) -> None:
        console.print(f"[dim][{i}/{total}][/] {query} [dim]-> {kept} new[/]")

    # The clock is read once, here at the edge, and passed down. Everything
    # below scores against this moment rather than its own.
    now = datetime.now(UTC)

    try:
        bounties: list[Bounty] = collect(
            gh, queries, max_per_query=args.max_per_query, on_progress=progress
        )
        if not bounties:
            console.print("[yellow]No bounties matched. Try dropping --lang.[/]")
            store.close()
            return 0

        console.print(
            f"[dim]resolving metadata for {len({b.repo for b in bounties})} repos...[/]"
        )
        bounties = enrich_repos(gh, bounties, store)

        weights = weights_from(config, languages)

        if args.deep:
            ranked = rank(bounties, weights, now)
            shortlist = [s.bounty for s in ranked if not s.bounty.claimed][: args.deep]
            console.print(f"[dim]deep-checking top {len(shortlist)} for claims...[/]")
            checked = {b.key: b for b in detect_claims(gh, shortlist)}
            bounties = [checked.get(b.key, b) for b in bounties]

        scored = rank(bounties, weights, now)

    except RateLimited as exc:
        console.print(f"[red]{exc}[/]")
        store.close()
        return 1

    known = store.known_keys()
    new_keys = {s.bounty.key for s in scored} - known

    results = [s for s in scored if passes_filters(s, args, min_amount, min_stars)]
    hidden = len(scored) - len(results)
    if args.new_only:
        results = [s for s in results if s.bounty.key in new_keys]

    # Applied last, so the cap operates on what you'd actually have been shown.
    results, dropped = cap_per_repo(results, per_repo)

    if not args.no_record:
        store.record(scored)
    store.close()

    shown = results[: args.limit]

    if args.json:
        render_json(shown, now, new_keys)
    elif not shown:
        console.print(
            "[yellow]Nothing passed your filters.[/] "
            + (
                "Everything was seen on a previous run."
                if args.new_only
                else "Try lowering --min-score or --min-amount."
            )
        )
    else:
        render_table(shown, now, new_keys, total=len(scored))
        if note := describe_dropped(dropped, per_repo):
            console.print(f"[dim]{note}[/]")
        if hidden:
            console.print(
                f"[dim]{hidden} hidden by filters (claimed / suspect payout / "
                f"below thresholds). Use --include-claimed, --include-suspect "
                f"or lower --min-score to see them.[/]"
            )
        if args.explain:
            render_explain(shown)

    return 0


if __name__ == "__main__":
    sys.exit(main())
