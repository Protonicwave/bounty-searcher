"""Terminal output.

Kept ASCII-only on purpose: the default Windows console is cp1252, and an
issue title with an emoji in it (very common on bounty issues) would otherwise
take down the whole run mid-table.
"""

from __future__ import annotations

import json
import sys
from contextlib import suppress
from io import TextIOWrapper
from typing import Any, cast

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from .models import Bounty


def _make_console(**kwargs: Any) -> Console:
    """A console that degrades unencodable characters instead of raising."""
    for stream in (sys.stdout, sys.stderr):
        # Not every stream is a reconfigurable text stream (piped, wrapped).
        with suppress(AttributeError, ValueError):
            cast(TextIOWrapper, stream).reconfigure(errors="replace")
    return Console(**kwargs)


console = _make_console()


def _money(b: Bounty) -> Text:
    if b.amount is None:
        return Text("?", style="dim")
    symbol = {"USD": "$", "EUR": "€", "GBP": "£"}.get(b.currency, "")
    value = f"{symbol}{b.amount:,.0f}"
    style = "bold green" if b.amount >= 500 else "green"
    return Text(value, style=style)


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


def render_table(
    bounties: list[Bounty],
    new_keys: set[str] | None = None,
    total: int | None = None,
) -> None:
    """Render the ranked table. `total` is how many were found before filtering,
    so the footer can't imply the list is everything that matched."""
    new_keys = new_keys or set()

    # No fixed widths on Repo/Issue -- rich divides the leftover space between
    # them. Pinning every column instead leaves them zero-width on an 80-col
    # terminal, which is where this actually gets run.
    # One line per bounty, always. `fold` turns an 80-column terminal into a
    # wall of wrapped fragments, and `ellipsis` renders its "..." as "?" on a
    # cp1252 console -- so crop, and drop the vertical rules to buy width.
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
    # Usually just "open" -- give its slack to the columns that identify the issue.
    table.add_column("Status", no_wrap=True, overflow="crop", min_width=8, ratio=1)

    for b in bounties:
        if b.claimed:
            status = Text(b.claim_reason or "claimed", style="red")
        elif b.suspect:
            status = Text(f"suspect: {b.suspect_reason}", style="magenta")
        else:
            status = Text("open", style="dim")

        table.add_row(
            Text("*", style="bold cyan") if b.key in new_keys else "",
            Text(f"{b.score:.0f}", style=_score_style(b.score)),
            _money(b),
            b.repo,
            Text(b.title, style=f"link {b.url}"),
            _lang(b.language),
            _age(b.age_days),
            str(b.comments),
            status,
        )

    console.print(table)

    count = (
        f"showing {len(bounties)} of {total} found"
        if total is not None and total != len(bounties)
        else f"{len(bounties)} bounties"
    )
    new_here = len(new_keys & {b.key for b in bounties})
    console.print(
        f"[dim]{count}"
        + (f", [cyan]*[/cyan][dim] = {new_here} new" if new_here else "")
        + ". Titles are clickable links.[/dim]"
    )


def render_explain(bounties: list[Bounty]) -> None:
    """Per-bounty score breakdown, for tuning the weights."""
    for b in bounties:
        console.print(f"\n[bold]{b.repo}#{b.number}[/bold]  {b.title}")
        console.print(f"[dim]{b.url}[/dim]")
        parts = " ".join(
            f"[{'green' if v > 0 else 'red'}]{k}{v:+.1f}[/]"
            for k, v in sorted(b.score_parts.items(), key=lambda kv: -abs(kv[1]))
        )
        console.print(f"  base+30.0 {parts}  =  [bold]{b.score:.0f}[/bold]")


def render_json(bounties: list[Bounty], new_keys: set[str] | None = None) -> None:
    new_keys = new_keys or set()
    payload = []
    for b in bounties:
        record = b.to_dict()
        record["is_new"] = b.key in new_keys
        payload.append(record)
    print(json.dumps(payload, indent=2))
