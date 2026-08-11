import { useInfiniteQuery, useQuery } from '@tanstack/react-query'

import { api, type BountyQuery } from '@/lib/api'
import { keys } from '@/lib/keys'
import type { BountyRow } from '@/lib/types'

/** What the list actually renders: one flat array, and how many matched. */
export interface Listing {
  rows: BountyRow[]
  total: number
}

/**
 * The corpus, a page at a time, joined end to end.
 *
 * Pages are fetched by keyset cursor rather than by offset, so a sweep writing
 * to the corpus underneath cannot make a row appear twice or not at all. The
 * flattening happens here so every consumer sees the same array identity and a
 * memoised row is not re-rendered by a page arriving further down the list.
 */
export function useBounties(query: BountyQuery) {
  return useInfiniteQuery({
    queryKey: keys.list(query),
    queryFn: ({ pageParam, signal }) => api.bounties(query, pageParam, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    select: (data): Listing => ({
      rows: data.pages.flatMap((page) => page.rows),
      // Every page carries the same total, so the first one is as good as any.
      total: data.pages[0]?.total ?? 0,
    }),
  })
}

/**
 * One bounty in full, for the detail pane.
 *
 * Kept for a while after the selection moves on, because moving back up the
 * list is the most common thing anybody does and refetching a body that has
 * not changed is a request nobody asked for.
 */
export function useBounty(id: number | null) {
  return useQuery({
    queryKey: keys.bounty(id ?? 0),
    queryFn: ({ signal }) => api.bounty(id ?? 0, signal),
    enabled: id !== null,
    staleTime: 60_000,
  })
}
