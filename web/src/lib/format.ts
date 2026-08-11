/**
 * Every value the interface displays is formatted here and nowhere else.
 *
 * Money, ages and counts appear in the list, the detail pane and the status
 * line, and the one thing worse than a bad format is three of them.
 */

const LOCALE = 'en-GB'

/** How many minor units make one major unit, which Intl already knows. */
const digits = new Map<string, number>()

function minorDigits(currency: string): number {
  const known = digits.get(currency)
  if (known !== undefined) return known
  const found =
    new Intl.NumberFormat(LOCALE, {
      style: 'currency',
      currency,
    }).resolvedOptions().maximumFractionDigits ?? 2
  digits.set(currency, found)
  return found
}

/**
 * A payout, as it is written in the list: `$500`, `£1,250`, `$50,000`.
 *
 * Whole amounts lose their decimals, because a column of `.00` is noise. An
 * unrecognised currency code is shown as it came rather than guessed at.
 */
export function formatMoney(minorUnits: number, currency: string): string {
  try {
    const scale = 10 ** minorDigits(currency)
    const whole = minorUnits % scale === 0
    return new Intl.NumberFormat(LOCALE, {
      style: 'currency',
      currency,
      // The narrow symbol is what keeps USD reading as `$` rather than `US$`
      // under a British locale.
      currencyDisplay: 'narrowSymbol',
      minimumFractionDigits: whole ? 0 : minorDigits(currency),
      maximumFractionDigits: whole ? 0 : minorDigits(currency),
    }).format(minorUnits / scale)
  } catch {
    return `${String(minorUnits)} ${currency}`
  }
}

/**
 * Tenths as a decimal, with a trailing zero dropped: 14 reads 1.4, 100 reads 10.
 *
 * The caller rounds to tenths in whole numbers rather than handing a fraction
 * to `toFixed`, whose answer at a boundary depends on which side of the value
 * a binary float happens to land.
 */
function fromTenths(tenths: number): string {
  const whole = Math.trunc(tenths / 10)
  const rest = tenths % 10
  return rest === 0 ? String(whole) : `${String(whole)}.${String(rest)}`
}

/**
 * A star or comment count at list density: `120`, `1.4k`, `32k`, `1.2m`.
 *
 * Precision falls away as the number grows, because the difference between
 * 31,900 and 32,400 stars has never changed anybody's mind.
 */
export function formatCount(value: number): string {
  const n = Math.max(0, Math.round(value))
  if (n < 1_000) return String(n)
  if (n < 10_000) return `${fromTenths(Math.round(n / 100))}k`
  if (n < 1_000_000) return `${String(Math.round(n / 1_000))}k`
  return `${fromTenths(Math.round(n / 100_000))}m`
}

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR
const YEAR = 365 * DAY

/**
 * How long ago, in one or two characters: `now`, `45m`, `6h`, `12d`, `2y`.
 *
 * A timestamp in the future reads as `now`. Clock skew between this machine
 * and GitHub is not worth a negative age in the interface.
 */
export function formatAge(at: string | Date, now: Date): string {
  const then = typeof at === 'string' ? new Date(at) : at
  const elapsed = now.getTime() - then.getTime()
  if (Number.isNaN(elapsed)) return '?'
  if (elapsed < MINUTE) return 'now'
  if (elapsed < HOUR) return `${String(Math.floor(elapsed / MINUTE))}m`
  if (elapsed < DAY) return `${String(Math.floor(elapsed / HOUR))}h`
  if (elapsed < YEAR) return `${String(Math.floor(elapsed / DAY))}d`
  return `${String(Math.floor(elapsed / YEAR))}y`
}

const clock = new Intl.DateTimeFormat(LOCALE, {
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

/** The wall clock, local: `14:22`. */
export function formatClock(at: string | Date): string {
  const then = typeof at === 'string' ? new Date(at) : at
  if (Number.isNaN(then.getTime())) return '?'
  return clock.format(then)
}

/**
 * When something happened, as the status line says it.
 *
 * Today gets the clock, because that is how you think about a scan you ran an
 * hour ago. Anything older gets its age, because `14:22` on an unnamed day is
 * worse than useless.
 */
export function formatWhen(at: string | Date, now: Date): string {
  const then = typeof at === 'string' ? new Date(at) : at
  if (Number.isNaN(then.getTime())) return '?'
  return then.toDateString() === now.toDateString()
    ? formatClock(then)
    : formatAge(then, now)
}
