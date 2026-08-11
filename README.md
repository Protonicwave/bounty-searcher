# bounty-searcher

Finds paid GitHub issues and ranks them by how likely you are to actually get
paid for one.

It queries GitHub's issue search directly rather than scraping bounty boards,
because most GitHub bounties never reach a board — they're created by a bot
comment (`/bounty 250`), a label (`💰 bounty`), or a maintainer typing `[$500]`
into a title. Aggregator sites only list their own platform's bounties, which
is why they always look out of date.

## Setup

```sh
pip install -e .
```

Set a GitHub token. It's optional but strongly recommended — it raises the
search limit from 10 to 30 requests/minute, and a full scan uses about a dozen.
Create one at <https://github.com/settings/tokens>; no scopes are needed for
public repos.

```sh
export GITHUB_TOKEN=ghp_...          # PowerShell: $env:GITHUB_TOKEN = "ghp_..."
```

Or, if you use `scan.bat`, just save the token as `token.txt` next to it — the
launcher reads it automatically. That file is gitignored; keep it that way.

## Use

```sh
python -m bounty_searcher --lang typescript
```

```
  Score      Pay   Repo               Issue                              Lang   Age  Cmt  Status
* 82        $500   SuperteamDAO/earn  Agent API: /api/agents/listings…   TS      5d    2  open
  43           ?   paraspell/xcm-too  [Bug bounty] XCM Analyser: unbo…   TS      3d    1  open
```

Titles are clickable links in most terminals. A `*` marks a bounty that wasn't
there last time you ran it.

Useful flags:

| Flag | What it does |
| --- | --- |
| `--lang X` | Search and favour a language. Repeatable. |
| `--min-amount N` | Hide bounties under `N`. Unpriced ones are kept — the figure is often negotiated in the thread. |
| `--min-stars N` | Hide small repos entirely. |
| `--per-repo N` | At most `N` bounties per repo, best-scoring first (default 3, `0` disables). Stops one project that filed six near-identical issues from taking over the list. |
| `--new-only` | Only what's appeared since your last run. |
| `--deep [N]` | Check the top `N` (default 15) for an existing PR or a "working on this" comment. Two extra API calls each. |
| `--explain` | Show the score breakdown per bounty. |
| `--json` | Machine-readable output. |
| `--include-claimed` / `--include-suspect` | Turn off the default filters. |
| `--reset-seen` | Forget history, so everything counts as new again. |

Settings can live in `config.toml` instead of flags — copy `config.example.toml`
and edit. Flags override the file.

## How the ranking works

The premise is that raw payout is a bad sort key. A $2,000 bounty on compiler
internals in a 90k-star repo is worth less to most people than a $150 bounty on
a small CLI they can fix tonight. So the score combines:

- **Payout**, with hard diminishing returns — `payout_halfway` (default $300)
  is the amount that earns half the maximum.
- **Language fit** against your `--lang` choices.
- **Effort proxy** from labels (`good first issue` up, `epic`/`rfc` down).
- **Freshness** — popular bounties are claimed within hours, so age is punished.
- **Competition** — every comment is one more person who has looked at it.
- **Repo size** — 100–20k stars is the sweet spot; huge repos are slow to merge
  outside PRs.
- **Claimed status** — a large penalty, since these are usually dead ends.

Run `--explain` to see each component, and tune any of them in `config.toml`.

## Spam filtering

GitHub issue search surfaces a lot of bounty-farming repos: zero-star projects
posting fake payouts (a real example from testing advertised **$50,000** on a
repo with 0 stars and an AI-generated issue body). Any priced bounty from a repo
under `credible_stars` (default 5) stars is flagged **suspect** and hidden, as is
an implausibly large payout on a mid-size repo. Forks are demoted, since cloned
template repos carry the same seeded "bounty" issue in every copy.

This will occasionally hide a legitimate brand-new project. `--include-suspect`
shows them, tagged with the reason.

## Running it on a schedule

The tool remembers what it has shown you in `~/.bounty-searcher/state.db`, so
`--new-only` is the mode that makes a cron job or Task Scheduler entry useful:

```sh
python -m bounty_searcher --lang typescript --new-only --min-score 50
```

That prints nothing on a quiet run, so it composes with a notifier.

## Known limits

- **Comment search is impossible.** GitHub's search API can't query issue
  comments, so bounties that exist *only* as an Algora/Polar bot comment on an
  otherwise-normal issue are invisible unless the bot also edits the body. This
  is the biggest coverage gap; closing it means integrating each platform's own
  API.
- **Claim detection is shallow by default** — just the assignee field. `--deep`
  checks for linked PRs and dibs comments, but costs two API calls per issue.
- Search returns at most 1000 results per query.

## Tests

```sh
pip install -e ".[dev]"
python -m pytest -q
```
