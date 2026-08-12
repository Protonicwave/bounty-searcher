import type { BountyRow } from './types'

/**
 * Where the repository would be cloned from.
 *
 * Taken from the host the issue itself is on rather than assumed, since the
 * corpus records the URL it was found at and that is the only host we know.
 */
export function cloneUrl(row: BountyRow): string {
  try {
    return `${new URL(row.url).origin}/${row.repo}.git`
  } catch {
    return `${row.repo}.git`
  }
}

/** The command you would actually paste, which is what gets copied. */
export function cloneCommand(row: BountyRow): string {
  return `git clone ${cloneUrl(row)}`
}
