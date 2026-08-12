"""Turning one search into hundreds of them.

GitHub will not return more than 1,000 results for any single query, however
many there are. That ceiling is the reason the old tool topped out at a couple
of hundred bounties, and no amount of paging gets round it.

What does get round it is asking a different question. A query restricted to
one month is a different query with its own 1,000 result allowance, so twelve
monthly windows multiply the ceiling twelvefold for no loss of coverage. The
same trick applies to star bands, and to sorting a saturated query backwards.

So the axes are: vocabulary, because there is no standard way to advertise a
bounty; time, because it is the cheapest way to slice the set; stars, because
the slices are disjoint and it doubles as a spam filter; and sort direction,
because a query that genuinely saturates hides its far end.

The plan is deterministic and ordered, most valuable first, and every entry
carries an estimated cost, so a sweep can be budgeted before it starts rather
than discovered to be four hours long half way through.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import date, timedelta

from ..config import ScanSettings
from ..sources.base import SourceQuery
from ..sources.github.search import NAME as SEARCH_SOURCE

log = logging.getLogger(__name__)

# Most queries in a monthly window return well under a page. Refinements only
# exist because their parent saturated, so they are expected to cost more.
ESTIMATED_PAGES = 2
ESTIMATED_REFINED_PAGES = 4

# An open-ended band such as ">10000" has no upper bound, and no repository
# will ever have this many stars.
NO_CEILING = 1_000_000_000


@dataclass(frozen=True, slots=True)
class PlannedQuery:
    """One search, and enough of how it was built to split it again."""

    query: str
    pages: int
    vocabulary: str
    window: tuple[date, date] | None = None
    stars: str | None = None
    language: str | None = None
    order: str = "desc"

    def as_source_query(self) -> SourceQuery:
        return SourceQuery(
            source=SEARCH_SOURCE,
            query=self.query,
            cost=self.pages,
            params=(("order", self.order),),
        )


def month_windows(as_of: date, months: int) -> list[tuple[date, date]]:
    """Calendar months back from today, newest first.

    The newest window stops at today rather than at the end of the month, so a
    sweep run on the 3rd does not ask GitHub about the rest of the month.
    """
    windows: list[tuple[date, date]] = []
    end = as_of
    for _ in range(max(0, months)):
        start = end.replace(day=1)
        windows.append((start, end))
        end = start - timedelta(days=1)
    return windows


class Planner:
    """Builds the query list, and splits the ones that saturate."""

    def __init__(self, settings: ScanSettings, as_of: date) -> None:
        self.settings = settings
        self.as_of = as_of

    def plan(self) -> list[PlannedQuery]:
        """Every query to run, ordered so that truncating loses the least.

        Windows are the outer loop, so a plan cut short by the request budget
        drops the oldest months and keeps full vocabulary coverage of the
        recent ones. Recent bounties are the ones still winnable, so that is
        the right thing to lose.
        """
        settings = self.settings
        months = month_windows(self.as_of, settings.lookback_months)
        windows: list[tuple[date, date] | None] = list(months) or [None]
        languages: tuple[str | None, ...] = settings.languages or (None,)

        planned: list[PlannedQuery] = []
        spent = 0
        dropped = 0

        for window in windows:
            for vocabulary in settings.vocabulary:
                for language in languages:
                    query = PlannedQuery(
                        query=self._compose(vocabulary, window, None, language),
                        pages=ESTIMATED_PAGES,
                        vocabulary=vocabulary,
                        window=window,
                        language=language,
                    )
                    if self._over_budget(spent + query.pages):
                        dropped += 1
                        continue
                    spent += query.pages
                    planned.append(query)

        if dropped:
            # Never truncate quietly: a short plan looks exactly like a thin
            # month unless it says so.
            log.warning(
                "request budget %s reached: %d queries planned, %d left out",
                settings.request_budget,
                len(planned),
                dropped,
            )
        return planned

    def refine(self, saturated: PlannedQuery) -> list[PlannedQuery]:
        """Follow-up queries for one that hit the ceiling.

        Star bands first, because they slice the set into disjoint pieces and
        recover the most for the fewest requests. Only once a band is itself
        saturated is it worth running backwards, which recovers the far end of
        that band for one more request. A band that saturates in both
        directions has more behind it than this can reach, and says so.
        """
        if saturated.stars is None:
            return [
                replace(
                    saturated,
                    query=self._compose(
                        saturated.vocabulary, saturated.window, band, saturated.language
                    ),
                    pages=ESTIMATED_REFINED_PAGES,
                    stars=band,
                )
                for band in self._bands()
            ]

        if saturated.order == "desc":
            return [replace(saturated, pages=ESTIMATED_REFINED_PAGES, order="asc")]

        log.warning("query still saturated after every split: %s", saturated.query)
        return []

    def _bands(self) -> tuple[str, ...]:
        """The star bands, clamped to the floor the base query already applies.

        Splitting a query must not widen it. A band lying entirely below the
        floor is dropped, one straddling it is raised to it, and the lowest
        surviving band is stretched down to it so the range stays continuous.
        """
        floor = self.settings.min_stars
        clamped = [
            band
            for band in (_clamp_band(raw, floor) for raw in self.settings.star_bands)
            if band is not None
        ]
        if clamped:
            clamped[0] = _lower_edge(clamped[0], floor)
        return tuple(clamped)

    def _over_budget(self, spent: int) -> bool:
        budget = self.settings.request_budget
        return budget > 0 and spent > budget

    def _compose(
        self,
        vocabulary: str,
        window: tuple[date, date] | None,
        stars: str | None,
        language: str | None,
    ) -> str:
        parts = [vocabulary, "state:open", "type:issue"]
        if window is not None:
            parts.append(f"created:{window[0].isoformat()}..{window[1].isoformat()}")
        if stars is not None:
            parts.append(f"stars:{stars}")
        elif self.settings.min_stars > 0:
            parts.append(f"stars:>={self.settings.min_stars}")
        if language is not None:
            parts.append(f"language:{language}")
        if self.settings.extra_qualifiers:
            parts.append(self.settings.extra_qualifiers)
        return " ".join(parts)


def _split_band(band: str) -> tuple[int, int]:
    """A band as (lowest, highest) star count it accepts."""
    if band.startswith(">"):
        return int(band.removeprefix(">").removeprefix("=")), NO_CEILING
    low, _, high = band.partition("..")
    return int(low), int(high)


def _clamp_band(band: str, floor: int) -> str | None:
    """The part of a band at or above the floor, or None if there is none."""
    low, high = _split_band(band)
    if high <= floor:
        return None
    return band if low >= floor else _rewrite(band, max(low, floor))


def _lower_edge(band: str, floor: int) -> str:
    """The band with its bottom stretched down to the floor."""
    low, _ = _split_band(band)
    return band if low <= floor else _rewrite(band, floor)


def _rewrite(band: str, low: int) -> str:
    _, high = _split_band(band)
    return f">={low}" if high == NO_CEILING else f"{low}..{high}"


def estimate_requests(queries: list[PlannedQuery]) -> int:
    """What a plan is expected to cost, in requests."""
    return sum(query.pages for query in queries)
