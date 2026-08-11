"""Extracting payouts from the messy places maintainers put them.

Bounties are advertised in at least four different shapes:

    label:  "💰 Bounty: $250"      title: "[$500] Fix the flaky retry logic"
    body:   "/bounty 100"          body:  "Algora bounty: **$1,000**"

There is no standard, so we try labels first (most reliable), then the title,
then the body. Bodies are the noisiest source, so code is blanked out first and
a `$PATH` in a shell snippet cannot become a $0 bounty.

Every match carries its offsets back with it. Blanking preserves length rather
than deleting, so those offsets still point at the right characters of the
original text and the interface can highlight the figure where it was written.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation

from .models import Amount, AmountField, Confidence, Provenance

_CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP"}

# Each pattern is named, and the name is recorded on the match, so a payout can
# be traced back to the rule that read it.
_AMOUNT_PATTERNS = (
    # Symbol-prefixed: $1,000 / $1.5k / £250
    (
        "symbol",
        re.compile(r"(?P<sym>[$€£])\s?(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<k>k\b)?", re.I),
    ),
    # Code-prefixed: USD 500 / EUR 300
    (
        "code-prefix",
        re.compile(
            r"\b(?P<code>USD|EUR|GBP)\s?(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<k>k\b)?", re.I
        ),
    ),
    # Code-suffixed: 500 USD
    (
        "code-suffix",
        re.compile(
            r"\b(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<k>k)?\s?(?P<code>USD|EUR|GBP)\b", re.I
        ),
    ),
    # Bare bounty-bot command: /bounty 250
    (
        "command",
        re.compile(r"/bounty\s+(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<k>k\b)?", re.I),
    ),
)

_CODE_FENCE = re.compile(r"```.*?```|~~~.*?~~~", re.S)
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)

# Labels that mean "this repo pays" even without a number on them.
BOUNTY_LABEL_HINTS = (
    "bounty",
    "bountied",
    "paid",
    "reward",
    "cash",
    "💰",
    "💵",
    "💸",
)

# Ignore absurd values: these are almost always parsing accidents (year
# numbers, issue IDs, byte counts) rather than real payouts.
MIN_PLAUSIBLE = Decimal(5)
MAX_PLAUSIBLE = Decimal(100_000)


def _blank(match: re.Match[str]) -> str:
    """Replace a match with spaces, so later offsets still line up."""
    return " " * (match.end() - match.start())


def clean_body(text: str) -> str:
    """Blank out code and HTML comments so their `$` noise cannot be misread.

    Length is preserved deliberately. Offsets into the returned string are
    valid offsets into the original.
    """
    text = _HTML_COMMENT.sub(_blank, text)
    text = _CODE_FENCE.sub(_blank, text)
    return _INLINE_CODE.sub(_blank, text)


def _confidence(field: AmountField, pattern: str) -> Confidence:
    """How much to trust a figure, given where and how it was found."""
    if field is AmountField.LABEL or pattern == "command":
        # A label is applied by a maintainer, and /bounty is a bot command that
        # actually moves money. Both are close to authoritative.
        return Confidence.HIGH
    if field is AmountField.TITLE:
        return Confidence.MEDIUM
    return Confidence.LOW


def _candidates(text: str, field: AmountField) -> list[Amount]:
    """Every plausible payout in one piece of text."""
    found: list[Amount] = []

    for name, pattern in _AMOUNT_PATTERNS:
        for m in pattern.finditer(text):
            try:
                value = Decimal(m.group("num").replace(",", ""))
            except InvalidOperation:
                continue
            if m.group("k"):
                value *= 1000
            if not MIN_PLAUSIBLE <= value <= MAX_PLAUSIBLE:
                continue

            groups = m.groupdict()
            if groups.get("sym"):
                currency = _CURRENCY_SYMBOLS.get(groups["sym"], "USD")
            elif groups.get("code"):
                currency = groups["code"].upper()
            else:
                currency = "USD"

            found.append(
                Amount.from_units(
                    value,
                    currency,
                    _confidence(field, name),
                    Provenance(field, name, m.start(), m.end(), m.group(0)),
                )
            )

    return found


def extract_amount(labels: Sequence[str], title: str, body: str) -> Amount | None:
    """Find the payout for an issue, or None if there isn't a readable one.

    Labels are searched first, then the title, then the body. When several
    figures appear in the same place we take the largest: bodies often carry a
    running list of raised amounts ("started at $50, now $300") and the final
    figure is the one that pays.
    """
    fields: list[tuple[AmountField, str]] = [
        (AmountField.LABEL, label) for label in labels
    ]
    fields.append((AmountField.TITLE, title))
    fields.append((AmountField.BODY, clean_body(body or "")))

    # Labels share a field, so they compete with each other before the title
    # gets a look in. Two labels both carrying a figure is rare but real.
    for field in (AmountField.LABEL, AmountField.TITLE, AmountField.BODY):
        hits = [
            amount
            for kind, text in fields
            if kind is field
            for amount in _candidates(text, field)
        ]
        if hits:
            return max(hits, key=lambda a: a.minor_units)

    return None


def looks_like_bounty(labels: Sequence[str], title: str, body: str) -> bool:
    """True if the issue advertises money, even when no amount is parseable.

    An unpriced "bounty" label is still worth surfacing: plenty of repos
    negotiate the number in the thread.
    """
    haystack = " ".join(labels).lower()
    if any(hint in haystack for hint in BOUNTY_LABEL_HINTS):
        return True

    if extract_amount(labels, title, body) is not None:
        return True

    text = f"{title} {clean_body(body or '')}".lower()
    return any(
        marker in text
        for marker in ("/bounty", "algora.io/bounties", "bounty is", "bounty for this")
    )
