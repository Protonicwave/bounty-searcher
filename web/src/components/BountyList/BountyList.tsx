import { useVirtualizer } from '@tanstack/react-virtual'
import { useEffect, useMemo, useRef } from 'react'

import type { BountyRow } from '@/lib/types'

import { Row } from './Row'

/** The row height as the theme sets it, where no stylesheet is loaded. */
const FALLBACK_ROW = 50

/** Rows kept mounted either side of the window, to cover a fast scroll. */
const OVERSCAN = 8

/** How close to the end is close enough to ask for the next page. */
const PREFETCH_WITHIN = 15

/**
 * The row height, read from the theme rather than repeated here.
 *
 * The virtualiser and the stylesheet have to agree on this number exactly or
 * the list drifts out of its own scrollbar, so there is one place it is set
 * and this reads it.
 */
function rowHeight(): number {
  const token = getComputedStyle(document.documentElement).getPropertyValue(
    '--spacing-row',
  )
  return Number.parseFloat(token) || FALLBACK_ROW
}

interface Props {
  rows: BountyRow[]
  selected: number
  onSelect: (index: number) => void
  nowMs: number
  hasNextPage: boolean
  isFetchingNextPage: boolean
  fetchNextPage: () => void
}

/**
 * The list, virtualised at a fixed row height.
 *
 * Only what is on screen is mounted, and the window is moved by translating
 * one wrapper rather than by positioning every row, so scrolling touches a
 * single transform. Rows themselves are memoised and never learn where they
 * are, which is what keeps ten thousand of them navigable at frame rate.
 */
export function BountyList({
  rows,
  selected,
  onSelect,
  nowMs,
  hasNextPage,
  isFetchingNextPage,
  fetchNextPage,
}: Props) {
  const scroller = useRef<HTMLDivElement>(null)
  const size = useMemo(() => rowHeight(), [])

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scroller.current,
    estimateSize: () => size,
    overscan: OVERSCAN,
  })

  const items = virtualizer.getVirtualItems()
  const first = items[0]
  const furthest = items.at(-1)?.index ?? 0

  // Ask for the next page before the scroll reaches the end of this one, so
  // the list never stops under a held key.
  useEffect(() => {
    if (
      hasNextPage &&
      !isFetchingNextPage &&
      furthest >= rows.length - PREFETCH_WITHIN
    ) {
      fetchNextPage()
    }
  }, [furthest, rows.length, hasNextPage, isFetchingNextPage, fetchNextPage])

  // Keep the selection on screen. Nothing happens when it already is, so a
  // click cannot make the list jump under the cursor.
  useEffect(() => {
    if (rows.length > 0) virtualizer.scrollToIndex(selected, { align: 'auto' })
  }, [selected, rows.length, virtualizer])

  return (
    <div ref={scroller} className="scrollbar-thin overflow-y-auto border-r border-line">
      <div className="relative w-full" style={{ height: virtualizer.getTotalSize() }}>
        <div
          className="absolute top-0 left-0 w-full"
          style={{ transform: `translateY(${String(first?.start ?? 0)}px)` }}
        >
          {items.map((item) => {
            const row = rows[item.index]
            return row ? (
              <Row
                key={row.id}
                row={row}
                index={item.index}
                selected={item.index === selected}
                nowMs={nowMs}
                onSelect={onSelect}
              />
            ) : null
          })}
        </div>
      </div>
    </div>
  )
}
