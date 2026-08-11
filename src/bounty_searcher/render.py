"""Terminal output.

Kept ASCII-only on purpose: the default Windows console is cp1252, and an issue
title with an emoji in it (very common on bounty issues) would otherwise take
down the whole run mid-table.
"""

from __future__ import annotations

import json
import sys
from contextlib import suppress
from datetime import datetime
from io import TextIOWrapper
from typing import Any, cast

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from .domain.models import Amount, ScoredBounty


def _make_console(**kwargs: Any) -> Console:
    """A console that degrades unencodable characters instead of raising."""
    for stream in (sys.stdout, sys.stderr):
        # Not every stream is a reconfigurable text stream (piped, wrapped).
        with suppress(AttributeError, ValueError):
            cast(TextIOWrapper, stream).reconfigure(errors="replace")
    return Console(**kwargs)


console = _make_console()

_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£"}


def format_money(amount: Amount) -> str:
    return f"{_SYMBOLS.get(amount.currency, '')}{amount.units:,.0f}"


def _money(amount: Amount | None) -> Text:
    if amount is None:
        return Text("?", style="dim")
    style = "bold green" if amount.minor_units >= 50_000 else "green"
    return Text(format_money(amount), style=style)


def _score_style(score: float) -> str:
    if score >= 65:
        return "bold green"
    if score >= 45:
        return "yellow"
    return "dim"


_LANG_ABBREV = {
    "typescript": "TS",
    "javascript": "JS",
    "python": "Py",
    "rust": "Rs",
    "golang": "Go",
    "c++": "C++",
    "c#": "C#",
    "ruby": "Rb",
    "java": "Java",
    "kotlin": "Kt",
    "swift": "Swift",
    "php": "PHP",
    "shell": "Sh",
}


def _lang(name: str | None) -> str:
    """Abbreviate so the column can stay narrow on an 80-col terminal."""
    if not name:
        return "-"
    return _LANG_ABBREV.get(name.lower(), name[:5])


def _age(days: float) -> str:
    if days < 1:
        return f"{days * 24:.0f}h"
    if days < 60:
        return f"{days:.0f}d"
    if days < 730:
        return f"{days / 30:.0f}mo"
    return f"{days / 365:.0f}y"  # "139mo" is both ugly and too wide


def describe_dropped(dropped: dict[str, int], cap: int) -> str:
    """One-line summary of what the per-repo cap collapsed, busiest first."""
    if not dropped:
        return ""

    ranked = sorted(dropped.items(), key=lambda kv: -kv[1])
    total = sum(dropped.values())
    shown = ", ".join(f"{repo} (+{n})" for repo, n in ranked[:3])
    if len(ranked) > 3:
        shown += f", and {len(ranked) - 3} more"
    return f"{total} collapsed by --per-repo {cap}: {shown}"


def to_dict(scored: ScoredBounty, as_of: datetime) -> dict[str, Any]:
    """The JSON record for one bounty, for `--json` and scheduled runs."""
    b = scored.bounty
    amount = b.amount
    return {
        "key": b.key,
        "source": b.source,
        "repo": b.repo,
        "number": b.number,
        "title": b.title,
        "url": b.url,
        "amount": float(amount.units) if amount else None,
        "currency": amount.currency if amount else None,
        "amount_source": amount.provenance.field.value if amount else "",
        "amount_confidence": amount.confidence.value if amount else None,
        "language": b.language,
        "stars": b.stars,
        "is_fork": b.is_fork,
        "suspect": scored.suspect,
        "suspect_reason": scored.suspect_reason or "",
        "labels": list(b.labels),
        "comments": b.comments,
        "assignee": b.assignee,
        "claimed": b.claimed,
        "claim_reason": b.claim_reason or "",
        "age_days": round(b.age_days(as_of), 1),
        "created_at": b.created_at.isoformat(),
        "updated_at": b.updated_at.isoformat(),
        "score": round(scored.score.total, 1),
        "score_parts": {
            part.component.value: round(part.value, 1)
            for part in scored.score.components
        },
    }


def render_table(
    bounties: list[ScoredBounty],
    as_of: datetime,
    new_keys: set[str] | None = None,
    total: int | None = None,
) -> None:
    """Render the ranked table. `total` is how many were found before filtering,
    so the footer cannot imply the list is everything that matched."""
    new_keys = new_keys or set()

    # No fixed widths on Repo/Issue: rich divides the leftover space between
    # them. Pinning every column instead leaves them zero-width on an 80-col
    # terminal, which is where this actually gets run.
    # One line per bounty, always. `fold` turns an 80-column terminal into a
    # wall of wrapped fragments, and `ellipsis` renders its "..." as "?" on a
    # cp1252 console, so crop, and drop the vertical rules to buy width.
    table = Table(
        show_lines=False,
        header_style="bold",
        expand=True,
        box=box.SIMPLE_HEAD,
        padding=(0, 1),
    )
    table.add_column("", width=1)  # new marker
    table.add_column("Score", justify="right", width=5)
    table.add_column("Pay", justify="right", width=7)
    table.add_column("Repo", no_wrap=True, overflow="crop", min_width=14, ratio=3)
    table.add_column("Issue", no_wrap=True, overflow="crop", min_width=20, ratio=4)
    table.add_column("Lang", width=5, no_wrap=True, overflow="crop")
    table.add_column("Age", justify="right", width=5)
    table.add_column("Cmt", justify="right", width=3)
    # Usually just "open": give its slack to the columns that identify the issue.
    table.add_column("Status", no_wrap=True, overflow="crop", min_width=8, ratio=1)

    for scored in bounties:
        b = scored.bounty
        if b.claim_reason:
            status = Text(b.claim_reason, style="red")
        elif scored.suspect_reason:
            status = Text(f"suspect: {scored.suspect_reason}", style="magenta")
        else:
            status = Text("open", style="dim")

        table.add_row(
            Text("*", style="bold cyan") if b.key in new_keys else "",
            Text(f"{scored.score.total:.0f}", style=_score_style(scored.score.total)),
            _money(b.amount),
            b.repo,
            Text(b.title, style=f"link {b.url}"),
            _lang(b.language),
            _age(b.age_days(as_of)),
            str(b.comments),
            status,
        )

    console.print(table)

    count = (
        f"showing {len(bounties)} of {total} found"
        if total is not None and total != len(bounties)
        else f"{len(bounties)} bounties"
    )
    new_here = len(new_keys & {s.bounty.key for s in bounties})
    console.print(
        f"[dim]{count}"
        + (f", [cyan]*[/cyan][dim] = {new_here} new" if new_here else "")
        + ". Titles are clickable links.[/dim]"
    )


def render_explain(bounties: list[ScoredBounty]) -> None:
    """Per-bounty score breakdown, for tuning the weights."""
    for scored in bounties:
        b = scored.bounty
        console.print(f"\n[bold]{b.repo}#{b.number}[/bold]  {b.title}")
        console.print(f"[dim]{b.url}[/dim]")
        parts = " ".join(
            f"[{'green' if part.value > 0 else 'red'}]"
            f"{part.component.value}{part.value:+.1f}[/]"
            for part in sorted(scored.score.components, key=lambda p: -abs(p.value))
            if part.value
        )
        console.print(
            f"  base{scored.score.base:+.1f} {parts}"
            f"  =  [bold]{scored.score.total:.0f}[/bold]"
        )
        if b.amount is not None:
            p = b.amount.provenance
            console.print(
                f"  [dim]{format_money(b.amount)} read from the {p.field.value}"
                f" via {p.pattern}: {p.text!r}"
                f" ({b.amount.confidence.value} confidence)[/dim]"
            )


def render_json(
    bounties: list[ScoredBounty], as_of: datetime, new_keys: set[str] | None = None
) -> None:
    new_keys = new_keys or set()
    payload = []
    for scored in bounties:
        record = to_dict(scored, as_of)
        record["is_new"] = scored.bounty.key in new_keys
        payload.append(record)
    print(json.dumps(payload, indent=2))
