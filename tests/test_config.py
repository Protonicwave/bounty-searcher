"""Reading settings off disk."""

from __future__ import annotations

from pathlib import Path

import pytest

from bounty_searcher.config import (
    DEFAULT_VOCABULARY,
    ConfigError,
    load_config,
    scan_settings,
    score_weights,
)
from bounty_searcher.domain.scoring import weights_hash


def write(tmp_path: Path, body: str) -> str:
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    return str(path)


def test_a_missing_optional_config_is_not_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "bounty_searcher.config.CONFIG_LOCATIONS", (tmp_path / "absent.toml",)
    )

    assert load_config(None) == {}


def test_a_config_asked_for_by_name_has_to_exist(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(str(tmp_path / "nope.toml"))


def test_settings_fall_back_to_the_defaults() -> None:
    settings = scan_settings({})

    assert settings.vocabulary == DEFAULT_VOCABULARY
    assert settings.lookback_months == 12


def test_the_scan_table_is_read(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        """
        [scan]
        vocabulary = ["label:bounty"]
        lookback_months = 3
        min_stars = 50
        watchlist = ["owner/name"]
        watch_comments = false
        request_budget = 120
        """,
    )

    settings = scan_settings(load_config(path))

    assert settings.vocabulary == ("label:bounty",)
    assert settings.lookback_months == 3
    assert settings.min_stars == 50
    assert settings.watchlist == ("owner/name",)
    assert settings.watch_comments is False
    assert settings.request_budget == 120


def test_languages_on_the_command_line_win(tmp_path: Path) -> None:
    path = write(tmp_path, '[scan]\nlanguages = ["rust"]\n')

    assert scan_settings(load_config(path)).languages == ("rust",)
    assert scan_settings(load_config(path), languages=("go",)).languages == ("go",)


def test_a_budget_of_zero_means_no_budget(tmp_path: Path) -> None:
    path = write(tmp_path, "[scan]\nrequest_budget = 0\n")

    # A sweep allowed no requests at all is never what anybody wants, so zero
    # is the way to say "plan the lot" in a file that cannot hold a null.
    assert scan_settings(load_config(path)).request_budget == 0


def test_the_scoring_table_is_read(tmp_path: Path) -> None:
    path = write(tmp_path, "[scoring]\npayout_halfway = 150.0\ncredible_stars = 20\n")

    weights = score_weights(load_config(path))

    assert weights.payout_halfway == 150.0
    assert weights.credible_stars == 20


def test_a_key_the_scorer_does_not_have_is_ignored(tmp_path: Path) -> None:
    path = write(tmp_path, "[scoring]\nnot_a_weight = 1\n")

    assert score_weights(load_config(path)) == score_weights({})


def test_an_array_weight_survives_being_hashed(tmp_path: Path) -> None:
    # The weights are hashed to stamp every score, and TOML has arrays where
    # the weights have tuples. Read straight through, the scoring pass dies.
    path = write(tmp_path, "[scoring]\nsweet_spot_stars = [200, 30000]\n")

    weights = score_weights(load_config(path))

    assert weights.sweet_spot_stars == (200, 30000)
    assert weights_hash(weights)
