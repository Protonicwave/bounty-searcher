import { useBounty } from '@/hooks/useBounties'
import type { BountyRow } from '@/lib/types'

import { Actions, type Action } from './Actions'
import { Body } from './Body'
import { Header } from './Header'
import { Provenance } from './Provenance'
import { ScoreBreakdown } from './ScoreBreakdown'

function Rule() {
  return <div className="my-[20px] h-px bg-line" />
}

interface Props {
  row: BountyRow | undefined
  nowMs: number
  onOpen: () => void
  onCopyClone: () => void
  /** What the copy action last did, shown in its place for a moment. */
  copied: boolean
}

/**
 * Everything about one bounty, in the order the question is asked: what is it,
 * why is it ranked there, what does it actually say, and what will you do.
 *
 * The heading and the score are drawn from the list row, which is already in
 * hand, so moving the selection never blanks the pane while a body loads.
 */
export function Detail({ row, nowMs, onOpen, onCopyClone, copied }: Props) {
  const detail = useBounty(row?.id ?? null)

  if (!row) {
    return <div className="scrollbar-thin overflow-y-auto bg-surface" />
  }

  const actions: Action[] = [
    { label: 'Open on GitHub', hint: 'enter', primary: true, onClick: onOpen },
    { label: copied ? 'Copied' : 'Copy clone', hint: 'c', onClick: onCopyClone },
  ]

  const body = detail.data?.body ?? ''
  // Offsets only mean anything against the text they were read from, so a
  // figure taken from a label or a comment marks nothing in the body.
  const range =
    row.amount && row.amount.provenance.field === 'body'
      ? { start: row.amount.provenance.start, end: row.amount.provenance.end }
      : null

  return (
    <div className="scrollbar-thin overflow-y-auto bg-surface pt-[20px] pr-[22px] pb-[26px] pl-[22px]">
      <Header row={row} nowMs={nowMs} />
      <Rule />
      <ScoreBreakdown total={row.score.total} components={row.score.components} />
      <Rule />
      <div className="mb-[12px] text-xs tracking-brand text-fg-dimmer">ISSUE</div>
      {detail.isPending ? (
        <p className="font-sans text-base text-fg-dimmer">Loading the issue.</p>
      ) : detail.isError ? (
        <p className="font-sans text-base text-fg-dimmer">
          The issue could not be read.
        </p>
      ) : (
        <>
          <Body source={body} range={range} />
          <Provenance amount={row.amount} body={body} />
        </>
      )}
      <Actions actions={actions} />
    </div>
  )
}
