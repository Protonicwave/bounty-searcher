import { formatCount, formatWhen } from '@/lib/format'
import type { FilterKey, Filters } from '@/lib/filters'
import type { Meta, Scan } from '@/lib/types'

import { FilterChips } from './FilterChips'
import { QuotaGauge } from './QuotaGauge'

interface Props {
  meta: Meta | undefined
  /** True while the first request is still out, so nothing is known yet. */
  loading: boolean
  failed: boolean
  filters: Filters
  onRemoveFilter: (key: FilterKey) => void
}

function Separator() {
  return <span className="text-fg-ghost">|</span>
}

/** What the last sweep did, or is doing. */
function scanned(scan: Scan | null | undefined, now: Date): string {
  if (!scan) return 'never scanned'
  if (scan.running) {
    return `scanning ${String(scan.completed)}/${String(scan.planned)}`
  }
  if (scan.status === 'failed') return 'last scan failed'
  if (scan.status === 'interrupted') return 'last scan interrupted'
  return `scanned ${formatWhen(scan.finished_at ?? scan.started_at, now)}`
}

/**
 * The status line. Never moves, never animates, always correct.
 *
 * It is the only chrome the interface has, so everything that would otherwise
 * want a panel of its own lives here: how much matched, what is narrowing it,
 * what is left of the quota, and when the corpus was last topped up.
 */
export function StatusLine({
  meta,
  loading,
  failed,
  filters,
  onRemoveFilter,
}: Props) {
  const now = new Date()
  const total = meta?.counts.total

  return (
    <div className="flex h-status shrink-0 items-center gap-[18px] border-b border-line px-[14px] text-xs tracking-status text-fg-dim select-none">
      <span className="text-fg tracking-brand">BOUNTY&nbsp;SEARCHER</span>
      <Separator />
      {failed ? (
        <span className="text-fg">api unreachable</span>
      ) : (
        <span>
          <span className="text-fg">
            {total === undefined ? (loading ? '' : '0') : formatCount(total)}
          </span>{' '}
          found
        </span>
      )}
      <FilterChips filters={filters} onRemove={onRemoveFilter} />

      <span className="ml-auto" />

      <QuotaGauge quota={meta?.quota} />
      <Separator />
      <span>{scanned(meta?.last_scan, now)}</span>
      <Separator />
      <span>
        <kbd className="border border-line px-[4px] py-px font-mono">/</kbd>{' '}
        search
      </span>
      <span>
        <kbd className="border border-line px-[4px] py-px font-mono">?</kbd> keys
      </span>
    </div>
  )
}
