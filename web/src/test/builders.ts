/**
 * Rows to render in tests, built from one default so a test names only what it
 * is actually about.
 */

import type { BountyRow, Component, ScoreComponent } from '@/lib/types'

const COMPONENTS: ScoreComponent[] = [
  'payout',
  'language',
  'effort',
  'freshness',
  'competition',
  'repository',
]

export function components(
  values: Partial<Record<ScoreComponent, number>> = {},
): Component[] {
  return COMPONENTS.map((component) => ({
    component,
    value: values[component] ?? 5,
    maximum: 15,
  }))
}

export function row(over: Partial<BountyRow> = {}): BountyRow {
  return {
    id: 1,
    key: 'owner/repo#7',
    source: 'search',
    repo: 'owner/repo',
    number: 7,
    title: 'Agent API ignores the pagination cursor',
    url: 'https://github.com/owner/repo/issues/7',
    state: 'open',
    labels: ['bounty'],
    comments: 2,
    assignee: null,
    language: 'TypeScript',
    stars: 1400,
    is_fork: false,
    claim_reason: null,
    suspect_reason: null,
    amount: {
      minor_units: 50_000,
      currency: 'USD',
      confidence: 'high',
      provenance: {
        field: 'body',
        pattern: 'dollar',
        start: 0,
        end: 4,
        text: '$500',
      },
    },
    created_at: '2026-06-01T12:00:00Z',
    updated_at: '2026-06-02T12:00:00Z',
    first_seen_at: '2026-06-02T12:00:00Z',
    changed_at: null,
    is_new: false,
    is_changed: false,
    score: {
      total: 82,
      base: 30,
      components: components(),
      weights_hash: 'abcd1234',
    },
    triage: { status: 'new', snooze_until: null, updated_at: null },
    ...over,
  }
}
