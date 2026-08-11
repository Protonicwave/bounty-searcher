import { memo } from 'react'

import { formatAge, formatCount, formatMoney } from '@/lib/format'
import type { BountyRow } from '@/lib/types'

import { ScoreRail } from './ScoreRail'

interface Props {
  row: BountyRow
  index: number
  /** The one thing about a row that changes without the row changing. */
  selected: boolean
  /** Frozen between ticks, so an age cannot re-render a row on its own. */
  nowMs: number
  onSelect: (index: number) => void
}

function Dot() {
  return <span className="text-fg-ghost">/</span>
}

/**
 * One bounty, two lines, at the density the mockup sets.
 *
 * Memoised, and the only prop that moves with the selection is a boolean. So
 * moving down the list re-renders exactly two rows, and each of those changes
 * one class: the row's background and its gutter bar. That constraint is what
 * holds the frame rate over ten thousand rows, and it is why the gutter is
 * always rendered rather than mounted when it is needed.
 */
export const Row = memo(function Row({
  row,
  index,
  selected,
  nowMs,
  onSelect,
}: Props) {
  // Demotion by subtraction: less contrast, never a red badge.
  const muted = row.claim_reason !== null || row.suspect_reason !== null
  const now = new Date(nowMs)

  return (
    <div
      // Selecting on mouse down rather than click, because the mouse is the
      // fallback here and a fallback should still feel immediate.
      onMouseDown={() => {
        onSelect(index)
      }}
      className={`relative grid h-row grid-cols-[76px_26px_62px_minmax(0,1fr)] items-start gap-[12px] border-b border-line-soft py-[9px] pr-[14px] pl-[12px] ${
        selected ? 'bg-accent-bg' : 'bg-transparent'
      }`}
    >
      {/* Selection is a gutter bar, never a border box: boxes fight the rules. */}
      <span
        className={`absolute top-0 bottom-0 left-0 w-[2px] ${
          selected ? 'bg-accent' : 'bg-transparent'
        }`}
      />
      {row.is_new && (
        <span className="absolute top-[14px] left-[5px] h-[3px] w-[3px] bg-accent" />
      )}

      <span className={muted ? 'opacity-40' : undefined}>
        <ScoreRail total={row.score.total} components={row.score.components} />
      </span>

      <span className={`text-right ${muted ? 'text-fg-dim' : 'text-fg'}`}>
        {Math.round(row.score.total)}
      </span>

      <span
        className={`text-right ${
          row.amount === null
            ? 'text-fg-dimmer'
            : row.suspect_reason !== null
              ? 'text-fg-dimmer line-through'
              : muted
                ? 'text-fg-dim'
                : 'text-fg'
        }`}
      >
        {row.amount === null
          ? '?'
          : formatMoney(row.amount.minor_units, row.amount.currency)}
      </span>

      <span className="min-w-0">
        <span className="flex min-w-0 items-baseline gap-[8px]">
          <span className={`flex-none ${muted ? 'text-fg-dimmer' : 'text-fg-dim'}`}>
            {row.repo}
          </span>
          <span
            className={`fade-right min-w-0 ${muted ? 'text-fg-dim' : 'text-fg'}`}
          >
            {row.title}
          </span>
        </span>
        <span className="mt-[3px] flex gap-[12px] text-xs text-fg-dimmer">
          {row.language !== null && (
            <>
              <span>{row.language}</span>
              <Dot />
            </>
          )}
          <span>{formatAge(row.created_at, now)}</span>
          <Dot />
          <span>{row.comments} cmt</span>
          {row.stars !== null && (
            <>
              <Dot />
              <span>{formatCount(row.stars)}</span>
            </>
          )}
          {row.claim_reason !== null && (
            <>
              <Dot />
              <span className="border border-line px-[4px]">claimed</span>
            </>
          )}
          {row.suspect_reason !== null && (
            <>
              <Dot />
              <span className="border border-line px-[4px]">
                suspect: {row.suspect_reason}
              </span>
            </>
          )}
        </span>
      </span>
    </div>
  )
})
