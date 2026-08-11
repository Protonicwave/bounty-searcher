"""The four saved views, defined once.

A view is a named filter and a sort, nothing more. They live here rather than
beside the API because the command line reads the same corpus and must mean the
same thing by "tonight" as the interface does.

Building one is pure: the caller supplies the moment the last completed scan
started, because that is the only outside fact any of them needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from ..domain.models import TriageStatus
from .bounties import BountyFilter, SortKey


class ViewName(StrEnum):
    TONIGHT = "tonight"
    PAYDAY = "payday"
    CHANGED = "changed"
    ALL = "all"


# A filter no bounty can satisfy, for the changed view before the first scan
# has completed. Stated as a filter rather than as a special case at the call
# site, so every view still resolves to exactly one filter and one sort.
_MATCHES_NOTHING = BountyFilter(min_score=float("inf"))


@dataclass(frozen=True, slots=True)
class View:
    """One named starting point, and what to say about it when it is empty."""

    name: ViewName
    title: str
    description: str
    filters: BountyFilter
    sort: SortKey


def build(name: ViewName, *, last_scan_started: datetime | None = None) -> View:
    """The view under this name.

    ``last_scan_started`` is what "changed" is measured against. A sweep stamps
    every row it touches with the moment it began, so a bounty that moved
    during the last one carries exactly that timestamp. With no completed scan
    to compare against, nothing has changed yet and the view is empty by
    construction.
    """
    match name:
        case ViewName.TONIGHT:
            return View(
                name=name,
                title="Tonight",
                description="undecided, unclaimed, best first",
                filters=BountyFilter(
                    statuses=(TriageStatus.NEW,),
                    include_claimed=False,
                    include_suspect=False,
                    include_unpriced=True,
                ),
                sort=SortKey.SCORE,
            )
        case ViewName.PAYDAY:
            return View(
                name=name,
                title="Payday",
                description="what pays most, still going",
                filters=BountyFilter(
                    include_claimed=False,
                    include_suspect=False,
                    # A caller sorting by money and setting a floor means the
                    # money, so an unreadable figure does not get the benefit
                    # of the doubt here the way it does everywhere else.
                    include_unpriced=False,
                ),
                sort=SortKey.PAYOUT,
            )
        case ViewName.CHANGED:
            # Deliberately not filtered by status. Something moving on a bounty
            # you dismissed is the one time that decision is worth revisiting.
            return View(
                name=name,
                title="Changed",
                description="already seen, something moved",
                filters=BountyFilter(
                    changed_after=last_scan_started,
                    first_seen_before=last_scan_started,
                    include_suspect=False,
                    include_unpriced=True,
                )
                if last_scan_started is not None
                else _MATCHES_NOTHING,
                sort=SortKey.SCORE,
            )
        case ViewName.ALL:
            return View(
                name=name,
                title="All",
                description="the whole corpus, nothing hidden",
                filters=BountyFilter(
                    include_claimed=True,
                    include_suspect=True,
                    include_unpriced=True,
                ),
                sort=SortKey.SCORE,
            )
