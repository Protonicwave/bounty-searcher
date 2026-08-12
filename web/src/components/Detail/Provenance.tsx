import { lineOf } from '@/lib/markdown'
import type { Amount, AmountField } from '@/lib/types'

/** Where a figure can come from, as it would be said out loud. */
const FOUND_IN: Record<AmountField, string> = {
  title: 'the title',
  body: 'the issue body',
  label: 'a label',
  comment: 'a comment',
}

interface Props {
  amount: Amount | null
  body: string
}

function Value({ children }: { children: string }) {
  return <b className="font-normal text-fg-dim">{children}</b>
}

/**
 * Where the money was read from.
 *
 * "Did it read that right" is the question nobody asks out loud, so the answer
 * is on screen whether or not it was asked. A figure taken from the body gets
 * its line as well, since that is the one place you can go and check.
 */
export function Provenance({ amount, body }: Props) {
  if (amount === null) {
    return (
      <div className="mt-[14px] font-mono text-xs text-fg-dimmer">
        No figure found. Scored as <Value>unpriced</Value>.
      </div>
    )
  }

  const { field, text } = amount.provenance
  return (
    <div className="mt-[14px] font-mono text-xs text-fg-dimmer">
      found in <Value>{FOUND_IN[field]}</Value>
      {field === 'body' && `, line ${String(lineOf(body, amount.provenance.start))}`}
      {' / read as '}
      <Value>{text}</Value>
      {' / '}
      <Value>{amount.confidence}</Value> confidence
    </div>
  )
}
