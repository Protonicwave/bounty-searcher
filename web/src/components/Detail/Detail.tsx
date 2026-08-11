import { useEffect, useState } from 'react'

import { useBounty } from '@/hooks/useBounties'
import type { BountyRow } from '@/lib/types'

import { Actions, type Action } from './Actions'
import { Body } from './Body'
import { Header } from './Header'
import { Provenance } from './Provenance'
import { ScoreBreakdown } from './ScoreBreakdown'

/** How long the copy action says it worked before going back to offering it. */
const CONFIRM_MS = 1_500

function Rule() {
  return <div className="my-[20px] h-px bg-line" />
}

/** Where the repository would be cloned from, taken from the issue's own host. */
function cloneUrl(row: BountyRow): string {
  try {
    return `${new URL(row.url).origin}/${row.repo}.git`
  } catch {
    return `${row.repo}.git`
  }
}

interface Props {
  row: BountyRow | undefined
  nowMs: number
}

/**
 * Everything about one bounty, in the order the question is asked: what is it,
 * why is it ranked there, what does it actually say, and what will you do.
 */
export function Detail({ row, nowMs }: Props) {
  const detail = useBounty(row?.id ?? null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!copied) return
    const id = setTimeout(() => {
      setCopied(false)
    }, CONFIRM_MS)
    return () => {
      clearTimeout(id)
    }
  }, [copied])

  if (!row) {
    return <div className="scrollbar-thin overflow-y-auto bg-surface" />
  }

  const actions: Action[] = [
    {
      label: 'Open on GitHub',
      hint: 'enter',
      primary: true,
      onClick: () => window.open(row.url, '_blank', 'noopener'),
    },
    {
      label: copied ? 'Copied' : 'Copy clone',
      hint: 'c',
      onClick: () => {
        void navigator.clipboard.writeText(`git clone ${cloneUrl(row)}`)
        setCopied(true)
      },
    },
  ]

  const body = detail.data?.body ?? ''
  // Offsets only mean anything against the text they were read from, so a
  // figure taken from a label or a comment marks nothing in the body.
  const range =
    row.amount && row.amount.provenance.field === 'body'
      ? {
          start: row.amount.provenance.start,
          end: row.amount.provenance.end,
        }
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
