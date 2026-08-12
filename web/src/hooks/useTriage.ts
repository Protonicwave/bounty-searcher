import {
  useMutation,
  useQueryClient,
  type InfiniteData,
  type QueryKey,
} from '@tanstack/react-query'
import { useCallback, useRef, useState } from 'react'

import { api } from '@/lib/api'
import { keys } from '@/lib/keys'
import type { BountyPage, TriageStatus } from '@/lib/types'

/** How long a decided row takes to leave. The only movement in the interface. */
export const COLLAPSE_MS = 150

/** How long a run of dismissals stays open for the next one to join it. */
const RUN_MS = 300

/** How long the undo offer stays on screen. */
const NOTICE_MS = 8_000

const NOTHING: ReadonlySet<number> = new Set()

/** What was done, so it can be said and taken back. */
export interface Notice {
  text: string
  /** Null while the transition is still in flight, which undo waits for. */
  token: string | null
}

const DONE: Record<TriageStatus, string> = {
  new: 'undecided',
  shortlisted: 'shortlisted',
  dismissed: 'dismissed',
  applied: 'applied',
  snoozed: 'snoozed',
}

interface Options {
  /** The list to edit optimistically, which is the one on screen. */
  listKey: QueryKey
  /** Whether deciding about a bounty takes it out of what is on screen. */
  decidedLeaves: boolean
  /** Called with the rows an undo brought back, so the selection can follow. */
  onRestore: (bountyIds: number[]) => void
}

/**
 * Deciding about bounties, and taking it back.
 *
 * Presses are gathered rather than sent one at a time, so a held dismiss key
 * costs one request and comes back under one undo token. The row leaves the
 * list on a timer rather than on the response: the corpus is local, the write
 * will succeed, and waiting for it would make the keyboard feel like a form.
 */
export function useTriage({ listKey, decidedLeaves, onRestore }: Options) {
  const client = useQueryClient()
  const [leaving, setLeaving] = useState<ReadonlySet<number>>(NOTHING)
  const [notice, setNotice] = useState<Notice | null>(null)

  const run = useRef<{ status: TriageStatus; ids: number[] } | null>(null)
  const closes = useRef<ReturnType<typeof setTimeout> | null>(null)
  const hides = useRef<ReturnType<typeof setTimeout> | null>(null)

  /** Take rows out of the page they are on, and off the count with them. */
  const drop = useCallback(
    (ids: readonly number[]) => {
      const gone = new Set(ids)
      client.setQueryData<InfiniteData<BountyPage, string | null>>(
        listKey,
        (data) => {
          if (!data) return data
          let removed = 0
          const pages = data.pages.map((page) => {
            const rows = page.rows.filter((row) => !gone.has(row.id))
            removed += page.rows.length - rows.length
            return { ...page, rows }
          })
          return {
            ...data,
            pages: pages.map((page) => ({
              ...page,
              total: Math.max(0, page.total - removed),
            })),
          }
        },
      )
    },
    [client, listKey],
  )

  const refresh = useCallback(() => {
    void client.invalidateQueries({ queryKey: listKey })
    void client.invalidateQueries({ queryKey: keys.meta })
  }, [client, listKey])

  const transition = useMutation({
    mutationFn: ({ ids, status }: { ids: number[]; status: TriageStatus }) =>
      api.triage(ids, status),
    onSuccess: (result) => {
      setNotice({
        text: `${String(result.bounty_ids.length)} ${DONE[result.status]}`,
        token: result.undo_token,
      })
      if (hides.current) clearTimeout(hides.current)
      hides.current = setTimeout(() => {
        setNotice(null)
      }, NOTICE_MS)
      refresh()
    },
    onError: () => {
      // The optimistic edit was a guess. The corpus is the answer.
      setNotice({ text: 'that did not save', token: null })
      setLeaving(NOTHING)
      refresh()
    },
  })

  const { mutate } = transition

  const flush = useCallback(() => {
    const held = run.current
    run.current = null
    if (closes.current) clearTimeout(closes.current)
    if (held) mutate(held)
  }, [mutate])

  /**
   * Decide about one bounty.
   *
   * Presses of the same key join the run in front of them. A different
   * decision closes the run first, so an undo never covers two answers.
   */
  const apply = useCallback(
    (bountyId: number, status: TriageStatus) => {
      const held = run.current
      if (held && held.status === status) held.ids.push(bountyId)
      else {
        flush()
        run.current = { status, ids: [bountyId] }
      }
      if (closes.current) clearTimeout(closes.current)
      closes.current = setTimeout(flush, RUN_MS)

      if (!decidedLeaves) return
      setLeaving((held2) => new Set([...held2, bountyId]))
      setTimeout(() => {
        drop([bountyId])
        setLeaving((held2) => {
          const rest = new Set(held2)
          rest.delete(bountyId)
          return rest
        })
      }, COLLAPSE_MS)
    },
    [decidedLeaves, drop, flush],
  )

  const reverse = useMutation({
    mutationFn: (token: string) => api.undo(token),
    onSuccess: (result) => {
      setNotice(null)
      refresh()
      onRestore(result.bounty_ids)
    },
  })

  const { mutate: reverseMutate } = reverse

  /** Take back the last decision, whichever key made it. */
  const undo = useCallback(() => {
    // Anything still gathering has not been sent, so there is nothing to undo
    // until it has been.
    flush()
    const token = notice?.token
    if (token) reverseMutate(token)
  }, [flush, notice, reverseMutate])

  const dismissNotice = useCallback(() => {
    setNotice(null)
  }, [])

  return { apply, undo, leaving, notice, dismissNotice }
}
