import { useCallback, useEffect, useMemo, useState } from 'react'

import { BountyList } from '@/components/BountyList'
import { Detail } from '@/components/Detail'
import { StatusLine } from '@/components/StatusLine'
import { useBounties } from '@/hooks/useBounties'
import { useMeta } from '@/hooks/useMeta'
import { useNow } from '@/hooks/useNow'
import type { BountyQuery } from '@/lib/api'
import { withoutFilter, type FilterKey, type Filters } from '@/lib/filters'
import type { BountyRow, SortKey, ViewName } from '@/lib/types'

/** One array identity for every empty list, so nothing re-renders on nothing. */
const NO_ROWS: BountyRow[] = []

/**
 * The shell: a status line that never moves, and two panes under it.
 *
 * Sixty to forty. The list needs the width for titles and the detail pane
 * needs a measure rather than a column, so widening it past forty would make
 * the prose worse, not better.
 */
export function App() {
  const meta = useMeta()
  const nowMs = useNow()

  // Fixed for now. Switching views and ordering arrive with the keymap, which
  // is the only thing that will ever set them.
  const view: ViewName = 'tonight'
  const sort: SortKey | null = null
  const [filters, setFilters] = useState<Filters>({})
  const query: BountyQuery = useMemo(() => ({ view, sort, filters }), [filters])

  const listing = useBounties(query)
  const rows = listing.data?.rows ?? NO_ROWS
  const [selected, setSelected] = useState(0)

  // A different question deserves its first answer, not the position you held
  // in the last one.
  useEffect(() => {
    setSelected(0)
  }, [query])

  const removeFilter = useCallback((key: FilterKey) => {
    setFilters((current) => withoutFilter(current, key))
  }, [])

  const { fetchNextPage } = listing
  const nextPage = useCallback(() => {
    void fetchNextPage()
  }, [fetchNextPage])

  return (
    <div className="flex h-full flex-col">
      <StatusLine
        meta={meta.data}
        total={listing.data?.total}
        view={view}
        loading={listing.isPending}
        failed={meta.isError || listing.isError}
        filters={filters}
        onRemoveFilter={removeFilter}
      />
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,60fr)_minmax(0,40fr)]">
        <BountyList
          rows={rows}
          selected={selected}
          onSelect={setSelected}
          nowMs={nowMs}
          hasNextPage={listing.hasNextPage}
          isFetchingNextPage={listing.isFetchingNextPage}
          fetchNextPage={nextPage}
        />
        <Detail row={rows[selected]} nowMs={nowMs} />
      </div>
    </div>
  )
}
