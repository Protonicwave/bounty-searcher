"""Extracting dollar amounts from the messy places maintainers put them.

Bounties are advertised in at least four different shapes:

    label:  "💰 Bounty: $250"      title: "[$500] Fix the flaky retry logic"
    body:   "/bounty 100"          body:  "Algora bounty: **$1,000**"

There is no standard, so we try labels first (most reliable), then the title,
then the body. Bodies are the noisiest source -- code blocks are stripped
first so a `$PATH` in a shell snippet doesn't become a $0 bounty.
"""

from __future__ import annotations

import re

# $1,000  |  $1.5k  |  $500.00  |  USD 250  |  250 USD  |  €300
_CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP"}

_AMOUNT_PATTERNS = [
    # Symbol-prefixed: $1,000 / $1.5k / £250
    re.compile(r"(?P<sym>[$€£])\s?(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<k>k\b)?", re.I),
    # Code-prefixed: USD 500 / EUR 300
    re.compile(
        r"\b(?P<code>USD|EUR|GBP)\s?(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<k>k\b)?", re.I
    ),
    # Code-suffixed: 500 USD
    re.compile(
        r"\b(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<k>k)?\s?(?P<code>USD|EUR|GBP)\b", re.I
    ),
    # Bare bounty-bot command: /bounty 250
    re.compile(r"/bounty\s+(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<k>k\b)?", re.I),
]

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

# Ignore absurd values -- these are almost always parsing accidents
# (year numbers, issue IDs, byte counts) rather than real payouts.
MIN_PLAUSIBLE = 5.0
MAX_PLAUSIBLE = 100_000.0


def _clean_body(text: str) -> str:
    """Strip code and HTML comments so their `$` noise can't be misread."""
    text = _HTML_COMMENT.sub(" ", text)
    text = _CODE_FENCE.sub(" ", text)
    text = _INLINE_CODE.sub(" ", text)
    return text


def _candidates(text: str) -> list[tuple[float, str]]:
    """Return every plausible (amount, currency) found in `text`."""
    found: list[tuple[float, str]] = []
    for pattern in _AMOUNT_PATTERNS:
        for m in pattern.finditer(text):
            raw = m.group("num").replace(",", "")
            try:
                value = float(raw)
            except ValueError:
                continue
            if m.groupdict().get("k"):
                value *= 1000

            groups = m.groupdict()
            if groups.get("sym"):
                currency = _CURRENCY_SYMBOLS.get(groups["sym"], "USD")
            elif groups.get("code"):
                currency = groups["code"].upper()
            else:
                currency = "USD"

            if MIN_PLAUSIBLE <= value <= MAX_PLAUSIBLE:
                found.append((value, currency))
    return found


def extract_amount(
    labels: list[str], title: str, body: str
) -> tuple[float | None, str, str]:
    """Find the bounty value for an issue.

    Returns ``(amount, currency, source)`` where source is one of
    ``label`` / ``title`` / ``body`` / ``""``. When several amounts appear in
    the same place we take the largest -- bodies often contain a running list
    of raised amounts ("started at $50, now $300") and the final figure is the
    one that pays.
    """
    for source, text in (
        ("label", " ".join(labels)),
        ("title", title),
        ("body", _clean_body(body or "")),
    ):
        hits = _candidates(text)
        if hits:
            amount, currency = max(hits, key=lambda h: h[0])
            return amount, currency, source

    return None, "USD", ""


def looks_like_bounty(labels: list[str], title: str, body: str) -> bool:
    """True if the issue advertises money, even when no amount is parseable.

    An unpriced "bounty" label is still worth surfacing -- plenty of repos
    negotiate the number in the thread.
    """
    haystack = " ".join(labels).lower()
    if any(hint in haystack for hint in BOUNTY_LABEL_HINTS):
        return True

    amount, _, _ = extract_amount(labels, title, body)
    if amount is not None:
        return True

    text = f"{title} {_clean_body(body or '')}".lower()
    return any(
        marker in text
        for marker in ("/bounty", "algora.io/bounties", "bounty is", "bounty for this")
    )
