from bounty_searcher.parse import extract_amount, looks_like_bounty


def test_amount_from_title_bracket() -> None:
    assert extract_amount([], "[$500] Fix flaky retry logic", "") == (
        500.0,
        "USD",
        "title",
    )


def test_label_wins_over_body() -> None:
    amount, _, source = extract_amount(
        ["Bounty: $250"], "Some issue", "maybe $10 later"
    )
    assert (amount, source) == (250.0, "label")


def test_bounty_bot_command() -> None:
    assert extract_amount([], "Add dark mode", "/bounty 100")[0] == 100.0


def test_k_suffix_expands() -> None:
    assert extract_amount([], "Perf regression", "We pay $1.5k for this")[0] == 1500.0


def test_currency_code_suffix() -> None:
    amount, currency, _ = extract_amount([], "Refactor", "costs 300 USD")
    assert (amount, currency) == (300.0, "USD")


def test_non_ascii_currency() -> None:
    assert extract_amount([], "Fix it", "reward: €300")[:2] == (300.0, "EUR")


def test_code_blocks_are_ignored() -> None:
    """A `$PATH` in a shell snippet must not be read as money."""
    amount, _, _ = extract_amount(
        [], "Set your $PATH", "run `export $PATH=1` then done"
    )
    assert amount is None


def test_fenced_code_ignored() -> None:
    body = "Here:\n```sh\necho $1000\n```\nno bounty yet"
    assert extract_amount([], "Question", body)[0] is None


def test_implausible_values_rejected() -> None:
    assert extract_amount([], "Issue", "error code $2")[0] is None
    assert extract_amount([], "Issue", "raised $999999999")[0] is None


def test_largest_amount_in_a_source_wins() -> None:
    body = "started at $50, now up to $300"
    assert extract_amount([], "Bump", body)[0] == 300.0


def test_unpriced_bounty_label_still_counts() -> None:
    assert looks_like_bounty(["bounty"], "no price here", "negotiable")
    assert extract_amount(["bounty"], "no price here", "negotiable")[0] is None


def test_plain_issue_is_not_a_bounty() -> None:
    assert not looks_like_bounty([], "Update the README", "typo in line 4")
