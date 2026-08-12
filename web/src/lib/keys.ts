/**
 * Query keys, listed in one place so a cache invalidation cannot miss one.
 */

import { searchParams, type BountyQuery } from './api'

export const keys = {
  meta: ['meta'] as const,
  /** Every page of the list, whatever the view. What triage invalidates. */
  bounties: ['bounties'] as const,
  /** One list, identified by the request it makes rather than by its shape. */
  list: (query: BountyQuery) => ['bounties', searchParams(query).toString()] as const,
  bounty: (id: number) => ['bounty', id] as const,
}
