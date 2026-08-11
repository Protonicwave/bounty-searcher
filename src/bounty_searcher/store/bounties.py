"""Reading and writing the bounty corpus.

Filtering and ordering happen in SQL, never in Python. The interface pages
through tens of thousands of rows, and the only way that stays instant is if
the database does the work and hands back exactly one page.
"""

from __future__ import annotations

import json
import sqlite3
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import blake2b

from ..domain.models import (
    Amount,
    AmountField,
    Bounty,
    ComponentScore,
    Confidence,
    Provenance,
    ScoreBreakdown,
    ScoreComponent,
    ScoredBounty,
    Triage,
    TriageStatus,
)
from ..domain.scoring import BASE_SCORE, ScoreWeights, score
from ..domain.select import assess_suspicion
from .db import from_ts, to_ts

_COLUMNS = (
    "repo",
    "number",
    "source",
    "title",
    "url",
    "state",
    "body",
    "labels",
    "comments",
    "assignee",
    "language",
    "stars",
    "is_fork",
    "claim_reason",
    "amount_minor",
    "amount_currency",
    "amount_confidence",
    "amount_field",
    "amount_pattern",
    "amount_start",
    "amount_end",
    "amount_text",
    "created_at",
    "updated_at",
    "first_seen_at",
    "last_seen_at",
    "changed_at",
    "content_hash",
)

# Everything a Bounty is built from except the body, which is the largest
# column and which neither scoring nor the list view reads.
_BOUNTY_COLUMNS = ", ".join(
    f"b.{c}"
    for c in ("id", *(c for c in _COLUMNS if c not in {"body", "content_hash"}))
)

_SCORE_COLUMNS = (
    "s.total, s.payout, s.language AS score_language, s.effort, s.freshness,"
    " s.competition, s.repository, s.suspect_reason, s.weights_hash"
)

_TRIAGE_COLUMNS = (
    "t.status AS triage_status, t.snooze_until, t.updated_at AS triage_updated_at"
)

_FROM = (
    "FROM bounty b"
    " JOIN bounty_score s ON s.bounty_id = b.id"
    " LEFT JOIN triage t ON t.bounty_id = b.id"
)

_UPSERT = f"""
INSERT INTO bounty ({", ".join(_COLUMNS)})
VALUES ({", ".join("?" * len(_COLUMNS))})
ON CONFLICT (repo, number) DO UPDATE SET
    {", ".join(f"{c} = excluded.{c}" for c in _COLUMNS if c != "first_seen_at")},
    changed_at = CASE
        WHEN bounty.content_hash <> excluded.content_hash THEN excluded.last_seen_at
        ELSE bounty.changed_at
    END
RETURNING id, first_seen_at, changed_at
"""


class SortKey(StrEnum):
    SCORE = "score"
    NEWEST = "newest"
    PAYOUT = "payout"


@dataclass(frozen=True, slots=True)
class _Order:
    """How one sort orders, seeks and reads its cursor value.

    `by` and `tie` are written to match an index exactly, columns and table
    alias included, or SQLite falls back to sorting the whole corpus in a
    temporary b-tree. `seek` is the same pair with unpriced rows given their
    sort value explicitly, since a NULL in a row-value comparison would drop
    every page after the first unpriced bounty.
    """

    by: str
    tie: str
    seek: str
    column: str


_ORDERS = {
    SortKey.SCORE: _Order("s.total", "s.bounty_id", "(s.total, s.bounty_id)", "total"),
    SortKey.NEWEST: _Order(
        "b.first_seen_at", "b.id", "(b.first_seen_at, b.id)", "first_seen_at"
    ),
    # Unpriced rows sort below every real payout: last under DESC, and -1 in
    # the seek, which agrees.
    SortKey.PAYOUT: _Order(
        "b.amount_minor", "b.id", "(COALESCE(b.amount_minor, -1), b.id)", "amount_minor"
    ),
}


@dataclass(frozen=True, slots=True)
class Cursor:
    """Where the previous page stopped: a sort value and the row id at it."""

    value: float
    bounty_id: int

    def encode(self) -> str:
        return urlsafe_b64encode(f"{self.value}:{self.bounty_id}".encode()).decode()

    @classmethod
    def decode(cls, token: str) -> Cursor:
        value, _, bounty_id = urlsafe_b64decode(token.encode()).decode().partition(":")
        return cls(float(value), int(bounty_id))


@dataclass(frozen=True, slots=True)
class BountyFilter:
    """What to leave out. Every field is applied in SQL."""

    language: str | None = None
    min_amount_minor: int | None = None
    min_stars: int | None = None
    max_age_days: float | None = None
    # Only what the corpus first saw at or after this moment, which is what
    # "new since the last scan" means once the corpus is the record.
    first_seen_after: datetime | None = None
    # The other half of that pair: only what the corpus already held before a
    # moment. With `changed_after` it says "something moved on a bounty I have
    # already seen", which is a different thing to notice than a new one.
    first_seen_before: datetime | None = None
    changed_after: datetime | None = None
    min_score: float | None = None
    statuses: tuple[TriageStatus, ...] = ()
    text: str | None = None
    include_suspect: bool = False
    include_claimed: bool = True
    # Whether a bounty with no readable figure survives an amount floor. The
    # number is often negotiated in the thread, so for a person reading the
    # list it should; for a caller asking "what pays at least this much", it
    # should not.
    include_unpriced: bool = False


@dataclass(frozen=True, slots=True)
class Page:
    rows: tuple[ScoredBounty, ...]
    total: int
    next_cursor: Cursor | None


@dataclass(frozen=True, slots=True)
class UpsertResult:
    # One per distinct bounty, in the order it was first given.
    ids: tuple[int, ...]
    inserted: int
    changed: int


def content_hash(b: Bounty) -> str:
    """Fingerprint of the fields that describe the issue rather than the scan.

    A difference here is a material change: something about the issue moved,
    not merely that we looked at it again.
    """
    payload = json.dumps(
        [
            b.title,
            b.body,
            b.state,
            list(b.labels),
            b.comments,
            b.assignee,
            b.language,
            b.stars,
            b.is_fork,
            b.claim_reason,
            b.amount.minor_units if b.amount else None,
            b.amount.currency if b.amount else None,
        ]
    )
    return blake2b(payload.encode(), digest_size=8).hexdigest()


# -- writing ---------------------------------------------------------------


def _row_values(b: Bounty, stamp: int) -> tuple[object, ...]:
    amount = b.amount
    provenance = amount.provenance if amount else None
    return (
        b.repo,
        b.number,
        b.source,
        b.title,
        b.url,
        b.state,
        b.body,
        json.dumps(list(b.labels)),
        b.comments,
        b.assignee,
        b.language,
        b.stars,
        int(b.is_fork),
        b.claim_reason,
        amount.minor_units if amount else None,
        amount.currency if amount else None,
        amount.confidence.value if amount else None,
        provenance.field.value if provenance else None,
        provenance.pattern if provenance else None,
        provenance.start if provenance else None,
        provenance.end if provenance else None,
        provenance.text if provenance else None,
        to_ts(b.created_at),
        to_ts(b.updated_at),
        stamp,  # first_seen_at, kept as it was on update
        stamp,  # last_seen_at
        stamp,  # changed_at, put back by the conflict clause when unchanged
        content_hash(b),
    )


# Keys per statement when asking which rows already exist. Two parameters
# each, well inside any SQLite parameter limit.
_EXISTS_CHUNK = 400


def _already_stored(
    conn: sqlite3.Connection, bounties: list[Bounty]
) -> set[tuple[str, int]]:
    """Which of these the corpus already holds.

    Asked before writing rather than inferred from the timestamps afterwards.
    A row written a moment ago by another query in the same sweep carries this
    sweep's timestamp too, so the timestamps cannot tell the two apart, and
    counting one bounty as two new ones would make the yield figures lie.
    """
    keys = [(b.repo, b.number) for b in bounties]
    found: set[tuple[str, int]] = set()
    for start in range(0, len(keys), _EXISTS_CHUNK):
        chunk = keys[start : start + _EXISTS_CHUNK]
        values = ", ".join("(?, ?)" for _ in chunk)
        rows = conn.execute(
            "SELECT repo, number FROM bounty"  # noqa: S608 - placeholders only
            f" WHERE (repo, number) IN (VALUES {values})",
            [field for key in chunk for field in key],
        )
        found.update((row["repo"], row["number"]) for row in rows)
    return found


def upsert_many(
    conn: sqlite3.Connection, bounties: list[Bounty], now: datetime
) -> UpsertResult:
    """Write a batch, preserving when each bounty was first seen.

    A row whose material fields differ from the stored ones has its
    ``changed_at`` moved forward, which is what the changed view reads.
    """
    # The same issue turns up under several queries, and writing it twice must
    # not count it twice.
    unique = list({(b.repo, b.number): b for b in bounties}.values())
    if not unique:
        return UpsertResult((), 0, 0)

    existing = _already_stored(conn, unique)
    ids: list[int] = []
    inserted = changed = 0
    stamp = to_ts(now)

    conn.execute("BEGIN")
    try:
        for b in unique:
            row = conn.execute(_UPSERT, _row_values(b, stamp)).fetchone()
            ids.append(row["id"])
            if (b.repo, b.number) not in existing:
                inserted += 1
            elif row["changed_at"] == stamp and row["first_seen_at"] != stamp:
                changed += 1
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return UpsertResult(tuple(ids), inserted, changed)


_WRITE_SCORES = """
INSERT INTO bounty_score
    (bounty_id, total, payout, language, effort, freshness, competition,
     repository, suspect_reason, weights_hash, scored_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (bounty_id) DO UPDATE SET
    total = excluded.total,
    payout = excluded.payout,
    language = excluded.language,
    effort = excluded.effort,
    freshness = excluded.freshness,
    competition = excluded.competition,
    repository = excluded.repository,
    suspect_reason = excluded.suspect_reason,
    weights_hash = excluded.weights_hash,
    scored_at = excluded.scored_at
"""


def write_scores(
    conn: sqlite3.Connection,
    scores: list[tuple[int, ScoreBreakdown, str | None]],
    now: datetime,
) -> None:
    """Store scores for rows that already exist."""
    stamp = to_ts(now)
    conn.execute("BEGIN")
    try:
        conn.executemany(
            _WRITE_SCORES,
            [
                (
                    bounty_id,
                    breakdown.total,
                    *(breakdown.value(component) for component in ScoreComponent),
                    reason,
                    breakdown.weights_hash,
                    stamp,
                )
                for bounty_id, breakdown, reason in scores
            ],
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def score_bounties(
    conn: sqlite3.Connection,
    weights: ScoreWeights,
    as_of: datetime,
    *,
    bounty_ids: list[int] | None = None,
    batch_size: int = 5_000,
) -> int:
    """Score the whole corpus, or just the given rows, from stored fields.

    No network and no body reads: one pass over columns the database already
    has. This is what makes a weight change cost milliseconds rather than a
    refetch.
    """
    sql = f"SELECT {_BOUNTY_COLUMNS} FROM bounty b"  # noqa: S608 - fixed columns
    params: tuple[object, ...] = ()
    if bounty_ids is not None:
        if not bounty_ids:
            return 0
        sql += f" WHERE b.id IN ({', '.join('?' * len(bounty_ids))})"
        params = tuple(bounty_ids)

    cursor = conn.execute(sql, params)
    written = 0
    while batch := cursor.fetchmany(batch_size):
        scores = []
        for row in batch:
            b = _bounty_from_row(row)
            reason = assess_suspicion(b, weights)
            scores.append(
                (
                    row["id"],
                    score(b, weights, as_of, suspect=reason is not None),
                    reason,
                )
            )
        write_scores(conn, scores, as_of)
        written += len(scores)

    return written


# -- reading ---------------------------------------------------------------


def _amount_from_row(row: sqlite3.Row) -> Amount | None:
    if row["amount_minor"] is None:
        return None
    return Amount(
        minor_units=row["amount_minor"],
        currency=row["amount_currency"],
        confidence=Confidence(row["amount_confidence"]),
        provenance=Provenance(
            field=AmountField(row["amount_field"]),
            pattern=row["amount_pattern"],
            start=row["amount_start"],
            end=row["amount_end"],
            text=row["amount_text"],
        ),
    )


def _bounty_from_row(row: sqlite3.Row, body: str = "") -> Bounty:
    return Bounty(
        source=row["source"],
        repo=row["repo"],
        number=row["number"],
        title=row["title"],
        url=row["url"],
        created_at=from_ts(row["created_at"]),
        updated_at=from_ts(row["updated_at"]),
        labels=tuple(json.loads(row["labels"])),
        body=body,
        comments=row["comments"],
        assignee=row["assignee"],
        state=row["state"],
        amount=_amount_from_row(row),
        language=row["language"],
        stars=row["stars"],
        is_fork=bool(row["is_fork"]),
        claim_reason=row["claim_reason"],
    )


def _triage_from_row(row: sqlite3.Row) -> Triage:
    if row["triage_status"] is None:
        return Triage()
    return Triage(
        status=TriageStatus(row["triage_status"]),
        snooze_until=(
            from_ts(row["snooze_until"]) if row["snooze_until"] is not None else None
        ),
        updated_at=from_ts(row["triage_updated_at"]),
    )


def _scored_from_row(row: sqlite3.Row, body: str = "") -> ScoredBounty:
    values = {
        ScoreComponent.PAYOUT: row["payout"],
        ScoreComponent.LANGUAGE: row["score_language"],
        ScoreComponent.EFFORT: row["effort"],
        ScoreComponent.FRESHNESS: row["freshness"],
        ScoreComponent.COMPETITION: row["competition"],
        ScoreComponent.REPOSITORY: row["repository"],
    }
    return ScoredBounty(
        bounty=_bounty_from_row(row, body),
        score=ScoreBreakdown(
            total=row["total"],
            base=BASE_SCORE,
            # Component maxima are a property of the weights, not of the row,
            # so they are recomputed by whoever renders them rather than
            # stored six more times per bounty.
            components=tuple(
                ComponentScore(component, value, 0.0)
                for component, value in values.items()
            ),
            weights_hash=row["weights_hash"],
        ),
        suspect_reason=row["suspect_reason"],
        triage=_triage_from_row(row),
        bounty_id=row["id"],
        first_seen_at=from_ts(row["first_seen_at"]),
        changed_at=from_ts(row["changed_at"]),
    )


def _fts_query(text: str) -> str:
    """Turn typed text into an FTS5 query that cannot be a syntax error.

    Every token is quoted, so punctuation a user types is matched rather than
    interpreted, and the last token matches as a prefix so results narrow as
    they type.
    """
    tokens = [token.replace('"', "") for token in text.split()]
    tokens = [token for token in tokens if token]
    if not tokens:
        return ""
    *head, last = tokens
    return " ".join([*(f'"{t}"' for t in head), f'"{last}"*'])


_STATUS_EXPR = (
    "CASE WHEN COALESCE(t.status, 'new') = 'snoozed'"
    " AND COALESCE(t.snooze_until, 0) <= ? THEN 'new'"
    " ELSE COALESCE(t.status, 'new') END"
)


def _where(filters: BountyFilter, as_of: datetime) -> tuple[list[str], list[object]]:
    """Clauses and their parameters, in the order they are bound."""
    clauses: list[str] = []
    params: list[object] = []

    if filters.language is not None:
        clauses.append("LOWER(b.language) = ?")
        params.append(filters.language.lower())
    if filters.min_amount_minor is not None:
        clauses.append(
            "(b.amount_minor IS NULL OR b.amount_minor >= ?)"
            if filters.include_unpriced
            else "b.amount_minor >= ?"
        )
        params.append(filters.min_amount_minor)
    if filters.min_score is not None:
        clauses.append("s.total >= ?")
        params.append(filters.min_score)
    if filters.min_stars is not None:
        clauses.append("COALESCE(b.stars, 0) >= ?")
        params.append(filters.min_stars)
    if filters.max_age_days is not None:
        clauses.append("b.created_at >= ?")
        params.append(to_ts(as_of - timedelta(days=filters.max_age_days)))
    if filters.first_seen_after is not None:
        clauses.append("b.first_seen_at >= ?")
        params.append(to_ts(filters.first_seen_after))
    if filters.first_seen_before is not None:
        clauses.append("b.first_seen_at < ?")
        params.append(to_ts(filters.first_seen_before))
    if filters.changed_after is not None:
        clauses.append("b.changed_at >= ?")
        params.append(to_ts(filters.changed_after))
    if filters.statuses:
        placeholders = ", ".join("?" * len(filters.statuses))
        clauses.append(f"{_STATUS_EXPR} IN ({placeholders})")
        params.append(to_ts(as_of))
        params.extend(status.value for status in filters.statuses)
    if not filters.include_suspect:
        clauses.append("s.suspect_reason IS NULL")
    if not filters.include_claimed:
        clauses.append("b.claim_reason IS NULL")
    if filters.text and (match := _fts_query(filters.text)):
        clauses.append(
            "b.id IN (SELECT rowid FROM bounty_fts WHERE bounty_fts MATCH ?)"
        )
        params.append(match)

    return clauses, params


def _cursor_at(row: sqlite3.Row, sort: SortKey) -> Cursor:
    value = row[_ORDERS[sort].column]
    return Cursor(float(value if value is not None else -1), row["id"])


def list_bounties(
    conn: sqlite3.Connection,
    *,
    as_of: datetime,
    filters: BountyFilter | None = None,
    sort: SortKey = SortKey.SCORE,
    cursor: Cursor | None = None,
    limit: int = 50,
) -> Page:
    """One page of the corpus, plus how many rows matched in total.

    Bodies are not loaded here. Use `get` for the one bounty on screen.
    """
    filters = filters or BountyFilter()
    order = _ORDERS[sort]
    clauses, params = _where(filters, as_of)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    total = conn.execute(
        f"SELECT COUNT(*) AS n {_FROM} {where}",  # noqa: S608 - clauses are literals
        params,
    ).fetchone()["n"]

    page_clauses, page_params = list(clauses), list(params)
    if cursor is not None:
        page_clauses.append(f"{order.seek} < (?, ?)")
        page_params.extend([cursor.value, cursor.bounty_id])
    page_where = f"WHERE {' AND '.join(page_clauses)}" if page_clauses else ""

    # One row more than asked for, so the presence of a next page is known
    # without a second count.
    rows = conn.execute(
        f"SELECT {_BOUNTY_COLUMNS}, {_SCORE_COLUMNS}, {_TRIAGE_COLUMNS}"  # noqa: S608
        f" {_FROM} {page_where} ORDER BY {order.by} DESC, {order.tie} DESC LIMIT ?",
        [*page_params, limit + 1],
    ).fetchall()

    next_cursor = _cursor_at(rows[limit - 1], sort) if len(rows) > limit else None
    return Page(
        rows=tuple(_scored_from_row(row) for row in rows[:limit]),
        total=total,
        next_cursor=next_cursor,
    )


def keys_first_seen_after(conn: sqlite3.Connection, moment: datetime) -> set[str]:
    """Identities the corpus first saw at or after a moment.

    What a scan just added, for the marker beside a row in the table.
    """
    return {
        f"{row['repo']}#{row['number']}"
        for row in conn.execute(
            "SELECT repo, number FROM bounty WHERE first_seen_at >= ?",
            (to_ts(moment),),
        )
    }


@dataclass(frozen=True, slots=True)
class CorpusCounts:
    """What the corpus holds, for the status line."""

    total: int
    priced: int
    suspect: int
    # Keyed by effective status, so an expired snooze is counted as new.
    by_status: dict[TriageStatus, int]


def counts(conn: sqlite3.Connection, as_of: datetime) -> CorpusCounts:
    """Corpus totals, in one pass rather than one query per number."""
    row = conn.execute(
        "SELECT COUNT(*) AS total,"  # noqa: S608 - fixed expression
        " SUM(b.amount_minor IS NOT NULL) AS priced,"
        f" SUM(s.suspect_reason IS NOT NULL) AS suspect {_FROM}"
    ).fetchone()

    grouped = conn.execute(
        f"SELECT {_STATUS_EXPR} AS effective, COUNT(*) AS n"  # noqa: S608
        f" {_FROM} GROUP BY effective",
        (to_ts(as_of),),
    )
    return CorpusCounts(
        total=row["total"],
        priced=row["priced"] or 0,
        suspect=row["suspect"] or 0,
        by_status={TriageStatus(item["effective"]): item["n"] for item in grouped},
    )


def forget_all(conn: sqlite3.Connection) -> int:
    """Empty the corpus. Scores, triage and the undo journal go with it."""
    return int(conn.execute("DELETE FROM bounty").rowcount)


def get(conn: sqlite3.Connection, bounty_id: int) -> ScoredBounty | None:
    """One bounty with its full body, score breakdown and triage state."""
    row = conn.execute(
        f"SELECT {_BOUNTY_COLUMNS}, b.body, {_SCORE_COLUMNS}, {_TRIAGE_COLUMNS}"
        f" {_FROM} WHERE b.id = ?",
        (bounty_id,),
    ).fetchone()
    return None if row is None else _scored_from_row(row, row["body"])
