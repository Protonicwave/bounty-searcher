/**
 * What is currently narrowing the corpus, and how to say it in one word.
 *
 * There is no filter sidebar. Active filters appear as removable chips in the
 * status line, so this is the whole of the filter state and the whole of its
 * presentation. A field that is absent means "leave the view's own answer
 * alone", which is exactly how the API reads a missing parameter.
 */

import { formatCount, formatMoney } from './format'
import type { TriageStatus } from './types'

export interface Filters {
  language?: string
  minAmountMinor?: number
  minStars?: number
  maxAgeDays?: number
  minScore?: number
  statuses?: TriageStatus[]
  q?: string
  includeSuspect?: boolean
  includeClaimed?: boolean
}

export type FilterKey = keyof Filters

export interface Chip {
  key: FilterKey
  label: string
}

/**
 * The amount floor crosses the wire as minor units with no currency attached,
 * so the chip labels it in the one the corpus is overwhelmingly written in.
 */
const FLOOR_CURRENCY = 'USD'

/**
 * One chip per active filter, in a fixed order.
 *
 * Fixed because the status line must not reshuffle itself when an unrelated
 * filter is added: a chip that moves is a chip you click by mistake.
 */
export function activeChips(filters: Filters): Chip[] {
  const chips: Chip[] = []
  const add = (key: FilterKey, label: string) => chips.push({ key, label })

  if (filters.q) add('q', `"${filters.q}"`)
  if (filters.language) add('language', filters.language)
  if (filters.minAmountMinor !== undefined) {
    add('minAmountMinor', `${formatMoney(filters.minAmountMinor, FLOOR_CURRENCY)}+`)
  }
  if (filters.minStars !== undefined) {
    add('minStars', `${formatCount(filters.minStars)}+ stars`)
  }
  if (filters.maxAgeDays !== undefined) {
    add('maxAgeDays', `under ${String(filters.maxAgeDays)}d`)
  }
  if (filters.minScore !== undefined) {
    add('minScore', `score ${String(filters.minScore)}+`)
  }
  if (filters.statuses && filters.statuses.length > 0) {
    add('statuses', filters.statuses.join(', '))
  }
  if (filters.includeClaimed !== undefined) {
    add('includeClaimed', filters.includeClaimed ? 'with claimed' : 'unclaimed')
  }
  if (filters.includeSuspect !== undefined) {
    add('includeSuspect', filters.includeSuspect ? 'with suspect' : 'no suspect')
  }
  return chips
}

/** The same filters without one of them, which is what removing a chip means. */
export function withoutFilter(filters: Filters, key: FilterKey): Filters {
  const kept = Object.entries(filters).filter(([name]) => name !== key)
  return Object.fromEntries(kept)
}
