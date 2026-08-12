import { formatCount, formatWhen } from '@/lib/format'
import type { Meta, View } from '@/lib/types'

interface Props {
  meta: Meta | undefined
  view: View | undefined
  /** True when something on top of the view is narrowing the corpus. */
  filtered: boolean
  nowMs: number
  onScan: () => void
  onShowEverything: () => void
  onClearFilters: () => void
}

function Offer({ label, hint, onClick }: { label: string; hint?: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex cursor-default items-center gap-[8px] border border-line px-[9px] py-[5px] text-xs text-fg-dim"
    >
      {label}
      {hint !== undefined && <span className="text-fg-ghost">{hint}</span>}
    </button>
  )
}

/** What the last sweep actually did, in one line. */
function covered(meta: Meta | undefined, nowMs: number): string {
  const scan = meta?.last_scan
  if (!scan) return 'No sweep has finished yet.'
  const when = formatWhen(scan.finished_at ?? scan.started_at, new Date(nowMs))
  return (
    `The last sweep ran ${when}: ${String(scan.completed)} of` +
    ` ${String(scan.planned)} queries, ${String(scan.new_bounties)} new.`
  )
}

/**
 * What you see when there is nothing to see.
 *
 * This is the state you will meet most evenings, so it gets the same attention
 * as a full list: what was looked at, when, and the shortest way to widen it.
 * An empty corpus is a different problem and says so separately.
 */
export function Quiet({
  meta,
  view,
  filtered,
  nowMs,
  onScan,
  onShowEverything,
  onClearFilters,
}: Props) {
  const empty = (meta?.counts.total ?? 0) === 0

  return (
    <div className="scrollbar-thin overflow-y-auto border-r border-line px-[22px] py-[26px]">
      {empty ? (
        <>
          <div className="text-base text-fg">Nothing has been scanned yet.</div>
          <p className="mt-[10px] max-w-measure font-sans text-base leading-[1.62] text-prose">
            The corpus fills up over several sweeps and then keeps what it
            found, so the first one is the long one. It runs in the background
            and you can keep working while it does.
          </p>
          <div className="mt-[18px] flex flex-wrap gap-[8px]">
            <Offer label="Run the first sweep" onClick={onScan} />
          </div>
        </>
      ) : (
        <>
          <div className="text-base text-fg">
            Nothing in {view?.title.toLowerCase() ?? 'this view'}
            {filtered ? ' under these filters' : ''}.
          </div>
          <p className="mt-[10px] max-w-measure font-sans text-base leading-[1.62] text-prose">
            {covered(meta, nowMs)} The corpus holds{' '}
            {formatCount(meta?.counts.total ?? 0)} bounties in total, so there
            is more here than this view is asking for.
          </p>
          <div className="mt-[18px] flex flex-wrap gap-[8px]">
            {filtered && <Offer label="Clear every filter" onClick={onClearFilters} />}
            <Offer label="Show everything" hint="4" onClick={onShowEverything} />
            <Offer label="Scan for more" onClick={onScan} />
          </div>
        </>
      )}
    </div>
  )
}
