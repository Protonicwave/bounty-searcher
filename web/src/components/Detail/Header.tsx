import { formatAge, formatCount } from '@/lib/format'
import type { BountyRow } from '@/lib/types'

interface Props {
  row: BountyRow
  nowMs: number
}

/**
 * Whose repository, what the issue is, and the four facts that decide whether
 * it is worth reading further.
 */
export function Header({ row, nowMs }: Props) {
  // The heading gives the slash room to breathe, which the list cannot afford.
  const slash = row.repo.indexOf('/')
  const heading =
    slash === -1
      ? row.repo
      : `${row.repo.slice(0, slash)} / ${row.repo.slice(slash + 1)}`
  const now = new Date(nowMs)

  return (
    <>
      <div className="text-xs tracking-meta text-fg-dim">{heading}</div>
      <h1 className="mt-[7px] mb-[9px] text-lg text-fg">{row.title}</h1>
      <div className="flex flex-wrap gap-[12px] text-xs text-fg-dimmer">
        {row.language !== null && <span>{row.language}</span>}
        <span>opened {formatAge(row.created_at, now)} ago</span>
        <span>
          {row.comments} {row.comments === 1 ? 'comment' : 'comments'}
        </span>
        {row.stars !== null && <span>{formatCount(row.stars)} stars</span>}
        <span>{row.claim_reason ?? 'unclaimed'}</span>
        {row.suspect_reason !== null && <span>suspect: {row.suspect_reason}</span>}
      </div>
    </>
  )
}
