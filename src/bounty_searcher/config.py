"""Settings, and where they are read from.

Two tables, because they answer different questions. ``[scan]`` decides what
the crawler goes and fetches, which costs quota and takes minutes. ``[search]``
decides what you are shown out of what it found, which costs nothing and is
changed on a whim. Confusing the two is how a display preference ends up
silently narrowing the corpus.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from .domain.scoring import ScoreWeights

CONFIG_LOCATIONS = (
    Path("config.toml"),
    Path.home() / ".bounty-searcher" / "config.toml",
)

# The vocabulary axis: every phrasing that has been observed to find bounties.
# There is no standard, so breadth here is the whole point. Precision comes
# from the parser and the scorer, never from the queries.
DEFAULT_VOCABULARY: tuple[str, ...] = (
    "label:bounty",
    "label:bountied",
    'label:"has bounty"',
    'label:"💰 bounty"',
    'label:"bounty 💵"',
    'label:"💎 bounty"',
    'label:"paid bounty"',
    'label:"bounty available"',
    'label:"$"',
    "bounty in:title",
    '"[$" in:title',
    "reward in:title",
    '"paid issue" in:title',
    '"/bounty" in:body',
    '"algora.io/bounties" in:body',
    '"polar.sh" in:body',
    "gitcoin in:body",
)

# Star bands used to break a query that has saturated. Each band is a disjoint
# slice of the same result set, so together they recover what the 1,000 result
# ceiling hid.
DEFAULT_STAR_BANDS: tuple[str, ...] = ("5..100", "100..1000", "1000..10000", ">10000")


class ConfigError(RuntimeError):
    """The configuration file was asked for by name and is not there."""


@dataclass(frozen=True, slots=True)
class ScanSettings:
    """What the crawler goes and fetches."""

    vocabulary: tuple[str, ...] = DEFAULT_VOCABULARY
    languages: tuple[str, ...] = ()
    # How far back the monthly windows reach. Each window is a separate query
    # with its own 1,000 result allowance, which is the main lever against the
    # search ceiling.
    lookback_months: int = 12
    star_bands: tuple[str, ...] = DEFAULT_STAR_BANDS
    # A floor on every query. Mirrors `credible_stars` in scoring: below it,
    # a payout is treated as spam anyway, so there is no point spending quota
    # fetching it.
    min_stars: int = 5
    extra_qualifiers: str = ""
    # Stop planning once the sweep would cost this many requests. Zero plans
    # the lot, which on the defaults is a long evening.
    request_budget: int = 600
    # Repositories to poll directly. Anything that has paid before, and
    # anything shortlisted, is added to these automatically.
    watchlist: tuple[str, ...] = ()
    # Whether to read repository comments looking for bounty bots. This is the
    # only way to see a bounty that exists solely as a comment.
    watch_comments: bool = True
    workers: int = 6


def load_config(explicit: str | None = None) -> dict[str, Any]:
    """Read the first configuration file that exists, or return nothing.

    A path given explicitly must exist. The default locations are optional by
    design, since the tool works with no configuration at all.
    """
    paths = (Path(explicit),) if explicit else CONFIG_LOCATIONS
    for path in paths:
        if path.is_file():
            with path.open("rb") as handle:
                return tomllib.load(handle)
    if explicit:
        raise ConfigError(f"config not found: {explicit}")
    return {}


def _strings(value: Any, fallback: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(value, list):
        return fallback
    return tuple(str(item) for item in value)


def scan_settings(
    config: dict[str, Any], *, languages: tuple[str, ...] = ()
) -> ScanSettings:
    """Build the scan settings, with command-line languages taking precedence."""
    table = config.get("scan") or {}
    defaults = ScanSettings()

    return ScanSettings(
        vocabulary=_strings(table.get("vocabulary"), defaults.vocabulary),
        languages=languages or _strings(table.get("languages"), ()),
        lookback_months=int(table.get("lookback_months", defaults.lookback_months)),
        star_bands=_strings(table.get("star_bands"), defaults.star_bands),
        min_stars=int(table.get("min_stars", defaults.min_stars)),
        extra_qualifiers=str(table.get("extra_qualifiers", defaults.extra_qualifiers)),
        request_budget=int(table.get("request_budget", defaults.request_budget)),
        watchlist=_strings(table.get("watchlist"), ()),
        watch_comments=bool(table.get("watch_comments", defaults.watch_comments)),
        workers=int(table.get("workers", defaults.workers)),
    )


def score_weights(
    config: dict[str, Any], languages: tuple[str, ...] = ()
) -> ScoreWeights:
    """Build the scoring weights, ignoring any key the scorer does not have.

    Lives here rather than with either entry point, because the command line
    and the interface have to score the corpus the same way.
    """
    known = {f.name for f in fields(ScoreWeights)}
    overrides: dict[str, Any] = {
        # TOML has arrays where the weights have tuples, and the weights are
        # hashed to stamp every score. A list would be unhashable and take the
        # whole scoring pass down with it.
        key: tuple(value) if isinstance(value, list) else value
        for key, value in (config.get("scoring") or {}).items()
        if key in known
    }
    overrides["preferred_languages"] = languages
    return ScoreWeights(**overrides)
