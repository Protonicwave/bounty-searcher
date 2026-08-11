import { useCallback, useState } from 'react'

import { StatusLine } from '@/components/StatusLine'
import { useMeta } from '@/hooks/useMeta'
import { withoutFilter, type FilterKey, type Filters } from '@/lib/filters'

/**
 * The shell: a status line that never moves, and two panes under it.
 *
 * Sixty to forty. The list needs the width for titles and the detail pane
 * needs a measure rather than a column, so widening it past forty would make
 * the prose worse, not better.
 */
export function App() {
  const meta = useMeta()
  const [filters, setFilters] = useState<Filters>({})

  const removeFilter = useCallback((key: FilterKey) => {
    setFilters((current) => withoutFilter(current, key))
  }, [])

  return (
    <div className="flex h-full flex-col">
      <StatusLine
        meta={meta.data}
        loading={meta.isPending}
        failed={meta.isError}
        filters={filters}
        onRemoveFilter={removeFilter}
      />
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,60fr)_minmax(0,40fr)]">
        <div className="scrollbar-thin overflow-y-auto border-r border-line" />
        <div className="scrollbar-thin overflow-y-auto bg-surface" />
      </div>
    </div>
  )
}
