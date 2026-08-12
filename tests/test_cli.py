"""The command line, reading the corpus rather than the network.

Everything here runs with --no-scan. The sweep itself is covered by the runner
suite; what these check is that the flags still mean what the README says.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bounty_searcher.cli import main
from bounty_searcher.store.db import Database
from tests.domain.builders import amount
from tests.store.corpus import bounty, fill


@pytest.fixture
def corpus(tmp_path: Path) -> str:
    """A small corpus with a good bounty, a cheap one and a suspect one."""
    path = tmp_path / "state.db"
    with Database(path) as db:
        fill(
            db.conn,
            [
                bounty(1, repo="good/repo", amount=amount(900)),
                bounty(2, repo="good/repo", amount=amount(20)),
                bounty(3, repo="good/repo", amount=None),
                bounty(4, repo="spam/farm", stars=0, amount=amount(9_000)),
            ],
        )
    return str(path)


def run(corpus: str, *flags: str) -> int:
    return main(["--no-scan", "--db", corpus, *flags])


def emitted(capsys: pytest.CaptureFixture[str]) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = json.loads(capsys.readouterr().out)
    return payload


def test_the_corpus_can_be_read_without_touching_the_network(
    corpus: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(corpus, "--json") == 0

    assert {row["key"] for row in emitted(capsys)} == {
        "good/repo#1",
        "good/repo#2",
        "good/repo#3",
    }


def test_a_suspect_payout_is_hidden_until_asked_for(
    corpus: str, capsys: pytest.CaptureFixture[str]
) -> None:
    run(corpus, "--json", "--include-suspect")

    assert "spam/farm#4" in {row["key"] for row in emitted(capsys)}


def test_an_amount_floor_keeps_the_unpriced(
    corpus: str, capsys: pytest.CaptureFixture[str]
) -> None:
    run(corpus, "--json", "--min-amount", "100")

    # The cheap one goes; the one with no figure at all stays, because that
    # number is often negotiated in the thread.
    assert {row["key"] for row in emitted(capsys)} == {"good/repo#1", "good/repo#3"}


def test_a_score_floor_is_applied(
    corpus: str, capsys: pytest.CaptureFixture[str]
) -> None:
    run(corpus, "--json", "--min-score", "100")

    assert emitted(capsys) == []


def test_the_per_repo_cap_collapses_a_noisy_project(
    corpus: str, capsys: pytest.CaptureFixture[str]
) -> None:
    run(corpus, "--json", "--per-repo", "1")

    assert len(emitted(capsys)) == 1


def test_nothing_is_new_when_nothing_was_scanned(
    corpus: str, capsys: pytest.CaptureFixture[str]
) -> None:
    run(corpus, "--json", "--new-only")

    assert emitted(capsys) == []


def test_forgetting_empties_the_corpus(
    corpus: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--db", corpus, "--forget"]) == 0

    run(corpus, "--json")
    assert emitted(capsys) == []


def test_a_named_config_that_is_not_there_is_an_error(corpus: str) -> None:
    assert run(corpus, "--config", "nowhere.toml") == 2


def test_the_table_renders(corpus: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(corpus) == 0

    # The table is the output. Progress and warnings go to stderr, so piping
    # either the table or --json gets the results and nothing else.
    captured = capsys.readouterr()
    assert "good/repo" in captured.out
    assert "good/repo" not in captured.err


def test_settings_come_from_the_config_file(
    corpus: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.toml"
    config.write_text("[search]\nmin_amount = 100\n", encoding="utf-8")

    run(corpus, "--json", "--config", str(config))

    assert {row["key"] for row in emitted(capsys)} == {"good/repo#1", "good/repo#3"}
