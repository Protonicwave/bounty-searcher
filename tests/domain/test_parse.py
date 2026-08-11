from bounty_searcher.domain.models import AmountField, Confidence
from bounty_searcher.domain.parse import (
    clean_body,
    extract_amount,
    looks_like_bounty,
)


def test_amount_from_title_bracket() -> None:
    amount = extract_amount([], "[$500] Fix flaky retry logic", "")
    assert amount is not None
    assert (amount.minor_units, amount.currency) == (50_000, "USD")
    assert amount.provenance.field is AmountField.TITLE


def test_label_wins_over_body() -> None:
    amount = extract_amount(["Bounty: $250"], "Some issue", "maybe $10 later")
    assert amount is not None
    assert amount.minor_units == 25_000
    assert amount.provenance.field is AmountField.LABEL


def test_bounty_bot_command() -> None:
    amount = extract_amount([], "Add dark mode", "/bounty 100")
    assert amount is not None and amount.minor_units == 10_000


def test_k_suffix_expands() -> None:
    amount = extract_amount([], "Perf regression", "We pay $1.5k for this")
    assert amount is not None and amount.minor_units == 150_000


def test_currency_code_suffix() -> None:
    amount = extract_amount([], "Refactor", "costs 300 USD")
    assert amount is not None
    assert (amount.minor_units, amount.currency) == (30_000, "USD")


def test_non_ascii_currency() -> None:
    amount = extract_amount([], "Fix it", "reward: €300")
    assert amount is not None
    assert (amount.minor_units, amount.currency) == (30_000, "EUR")


def test_code_blocks_are_ignored() -> None:
    """A `$PATH` in a shell snippet must not be read as money."""
    assert (
        extract_amount([], "Set your $PATH", "run `export $PATH=1` then done") is None
    )


def test_fenced_code_ignored() -> None:
    body = "Here:\n```sh\necho $1000\n```\nno bounty yet"
    assert extract_amount([], "Question", body) is None


def test_implausible_values_rejected() -> None:
    assert extract_amount([], "Issue", "error code $2") is None
    assert extract_amount([], "Issue", "raised $999999999") is None


def test_largest_amount_in_a_source_wins() -> None:
    amount = extract_amount([], "Bump", "started at $50, now up to $300")
    assert amount is not None and amount.minor_units == 30_000


def test_unpriced_bounty_label_still_counts() -> None:
    assert looks_like_bounty(["bounty"], "no price here", "negotiable")
    assert extract_amount(["bounty"], "no price here", "negotiable") is None


def test_plain_issue_is_not_a_bounty() -> None:
    assert not looks_like_bounty([], "Update the README", "typo in line 4")


def test_cleaning_a_body_preserves_offsets() -> None:
    """Offsets are only useful if they still index the original text."""
    body = "run `echo $9` then we pay $300"
    assert len(clean_body(body)) == len(body)

    amount = extract_amount([], "Pay up", body)
    assert amount is not None
    p = amount.provenance
    assert body[p.start : p.end] == p.text == "$300"


def test_provenance_records_the_matching_rule() -> None:
    amount = extract_amount([], "Fix", "/bounty 250")
    assert amount is not None
    assert amount.provenance.pattern == "command"


def test_confidence_falls_with_the_quality_of_the_source() -> None:
    label = extract_amount(["bounty: $200"], "t", "")
    title = extract_amount([], "[$200] t", "")
    body = extract_amount([], "t", "we might pay $200")
    assert label is not None and title is not None and body is not None
    assert label.confidence is Confidence.HIGH
    assert title.confidence is Confidence.MEDIUM
    assert body.confidence is Confidence.LOW


def test_amount_units_round_trip_without_float_error() -> None:
    amount = extract_amount([], "[$1,234.56] t", "")
    assert amount is not None
    assert amount.minor_units == 123_456
    assert str(amount.units) == "1234.56"
