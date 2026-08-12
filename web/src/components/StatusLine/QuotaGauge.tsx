import type { Quota } from '@/lib/types'

interface Props {
  quota: Quota | null | undefined
}

/**
 * What is left of the search budget, small enough to ignore until it matters.
 *
 * The search bucket is the one that binds: thirty requests a minute against
 * five thousand an hour for everything else. It reads null until a sweep has
 * run in this process, because there is no honest way to know the remaining
 * budget without having asked GitHub.
 */
export function QuotaGauge({ quota }: Props) {
  const bucket = quota?.search
  const paused = quota?.paused_until != null
  const fraction =
    bucket && bucket.limit > 0
      ? Math.min(1, Math.max(0, bucket.remaining / bucket.limit))
      : 0

  return (
    <span
      className="flex items-center gap-[7px]"
      title={
        paused
          ? 'Waiting out a secondary rate limit'
          : bucket
            ? 'Search requests remaining this minute'
            : 'No sweep has run yet, so the remaining budget is unknown'
      }
    >
      quota
      <span className="block h-[3px] w-[46px] bg-line">
        <span
          className="block h-full bg-fg-dim"
          style={{ width: `${String(fraction * 100)}%` }}
        />
      </span>
      {paused ? (
        <span>paused</span>
      ) : bucket ? (
        <span>
          <span className="text-fg">{bucket.remaining}</span>/{bucket.limit}
        </span>
      ) : (
        <span>unknown</span>
      )}
    </span>
  )
}
