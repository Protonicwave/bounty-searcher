"""The planner is pure, so these are values in and values out."""

from __future__ import annotations

from datetime import date
from typing import Any

from bounty_searcher.config import ScanSettings
from bounty_searcher.scan.planner import (
    ESTIMATED_PAGES,
    PlannedQuery,
    Planner,
    estimate_requests,
    month_windows,
)

AS_OF = date(2026, 8, 11)


def settings(**kwargs: Any) -> ScanSettings:
    """Two vocabulary terms and one month, so a plan is small enough to read."""
    defaults: dict[str, Any] = {
        "vocabulary": ("label:bounty", "bounty in:title"),
        "lookback_months": 1,
        "min_stars": 5,
        "request_budget": 0,
    }
    defaults.update(kwargs)
    return ScanSettings(**defaults)


def planner(**kwargs: Any) -> Planner:
    return Planner(settings(**kwargs), AS_OF)


def test_windows_are_calendar_months_newest_first() -> None:
    windows = month_windows(AS_OF, 3)

    assert windows == [
        # The newest window stops today rather than at the end of the month.
        (date(2026, 8, 1), date(2026, 8, 11)),
        (date(2026, 7, 1), date(2026, 7, 31)),
        (date(2026, 6, 1), date(2026, 6, 30)),
    ]


def test_windows_cross_a_year_boundary() -> None:
    windows = month_windows(date(2026, 1, 15), 2)

    assert windows[1] == (date(2025, 12, 1), date(2025, 12, 31))


def test_no_lookback_asks_for_no_windows() -> None:
    assert month_windows(AS_OF, 0) == []


def test_a_query_carries_the_window_and_the_star_floor() -> None:
    planned = planner().plan()

    assert planned[0].query == (
        "label:bounty state:open type:issue created:2026-08-01..2026-08-11 stars:>=5"
    )


def test_the_axes_multiply() -> None:
    planned = planner(lookback_months=3, languages=("rust", "go")).plan()

    # Two terms, three months, two languages.
    assert len(planned) == 12
    assert "language:rust" in planned[0].query
    assert "language:go" in planned[1].query


def test_extra_qualifiers_are_glued_onto_every_query() -> None:
    planned = planner(extra_qualifiers="-repo:noisy/monorepo").plan()

    assert all("-repo:noisy/monorepo" in query.query for query in planned)


def test_the_plan_is_ordered_so_truncation_loses_the_oldest_months() -> None:
    full = planner(lookback_months=6).plan()
    budgeted = planner(lookback_months=6, request_budget=4 * ESTIMATED_PAGES).plan()

    assert len(budgeted) == 4
    # The kept queries are the first four of the full plan, which is the two
    # newest months in full rather than a scattering of every month.
    assert [query.query for query in budgeted] == [query.query for query in full[:4]]


def test_a_cost_estimate_comes_back_with_the_plan() -> None:
    planned = planner(lookback_months=2).plan()

    assert estimate_requests(planned) == 4 * ESTIMATED_PAGES


def test_a_planned_query_becomes_a_unit_of_work() -> None:
    planned = planner().plan()[0]
    query = planned.as_source_query()

    assert query.source == "github-search"
    assert query.cost == ESTIMATED_PAGES
    assert query.param("order", "desc") == "desc"


def test_a_saturated_query_splits_into_star_bands() -> None:
    planned = planner().plan()[0]

    refined = planner().refine(planned)

    assert [query.stars for query in refined] == [
        "5..100",
        "100..1000",
        "1000..10000",
        ">10000",
    ]
    # The band replaces the floor rather than being added beside it.
    assert "stars:5..100" in refined[0].query
    assert "stars:>=5" not in refined[0].query


def test_splitting_a_query_never_widens_it() -> None:
    plan = planner(min_stars=500)

    refined = plan.refine(plan.plan()[0])

    # The band below the floor goes entirely, and the one straddling it is
    # raised to it rather than quietly reintroducing 100-star repositories.
    assert [query.stars for query in refined] == [
        "500..1000",
        "1000..10000",
        ">10000",
    ]


def test_without_a_floor_the_bands_reach_all_the_way_down() -> None:
    plan = planner(min_stars=0)

    refined = plan.refine(plan.plan()[0])

    # The lowest band stretches to zero, or repositories with four stars would
    # be covered by the unsplit query and by nothing after it.
    assert refined[0].stars == "0..100"
    assert "stars:" not in plan.plan()[0].query


def test_a_saturated_band_is_run_backwards() -> None:
    plan = planner()
    band = plan.refine(plan.plan()[0])[0]

    refined = plan.refine(band)

    assert len(refined) == 1
    assert refined[0].order == "asc"
    assert refined[0].as_source_query().param("order", "desc") == "asc"
    # Same query, other end of it, so the recorded identity has to differ.
    assert refined[0].as_source_query().key != band.as_source_query().key


def test_a_query_saturated_in_both_directions_has_nothing_left_to_try() -> None:
    plan = planner()
    exhausted = PlannedQuery(
        query="q", pages=4, vocabulary="label:bounty", stars="5..100", order="asc"
    )

    assert plan.refine(exhausted) == []
