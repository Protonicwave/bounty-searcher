import { describe, expect, it } from 'vitest'

import {
  formatAge,
  formatClock,
  formatCount,
  formatMoney,
  formatWhen,
} from './format'

describe('formatMoney', () => {
  it('drops the decimals on a whole amount', () => {
    expect(formatMoney(50_000, 'USD')).toBe('$500')
    expect(formatMoney(100_000, 'GBP')).toBe('£1,000')
  })

  it('keeps them when there is a remainder', () => {
    expect(formatMoney(50_050, 'USD')).toBe('$500.50')
  })

  it('uses the narrow symbol, so USD is not US$', () => {
    expect(formatMoney(5_000_000, 'USD')).toBe('$50,000')
  })

  it('respects a currency with no minor unit', () => {
    expect(formatMoney(1_200, 'JPY')).toBe('¥1,200')
  })

  it('shows an unrecognised code rather than guessing at it', () => {
    expect(formatMoney(500, 'NOTACURRENCY')).toBe('500 NOTACURRENCY')
  })
})

describe('formatCount', () => {
  it('leaves anything under a thousand alone', () => {
    expect(formatCount(0)).toBe('0')
    expect(formatCount(120)).toBe('120')
    expect(formatCount(999)).toBe('999')
  })

  it('keeps one decimal up to ten thousand', () => {
    expect(formatCount(1_400)).toBe('1.4k')
    expect(formatCount(3_600)).toBe('3.6k')
    expect(formatCount(9_800)).toBe('9.8k')
  })

  it('drops a trailing zero rather than showing 1.0k', () => {
    expect(formatCount(1_000)).toBe('1k')
  })

  it('rounds to whole thousands above ten thousand', () => {
    expect(formatCount(17_000)).toBe('17k')
    expect(formatCount(32_400)).toBe('32k')
  })

  it('rounds up across the band rather than showing 10.0k', () => {
    expect(formatCount(9_950)).toBe('10k')
  })

  it('moves to millions when it has to', () => {
    expect(formatCount(1_200_000)).toBe('1.2m')
  })
})

describe('formatAge', () => {
  const now = new Date('2026-08-11T14:22:00Z')
  const ago = (ms: number) => new Date(now.getTime() - ms)

  it('calls anything within the minute now', () => {
    expect(formatAge(ago(30_000), now)).toBe('now')
  })

  it('steps up through minutes, hours, days and years', () => {
    expect(formatAge(ago(45 * 60_000), now)).toBe('45m')
    expect(formatAge(ago(6 * 3_600_000), now)).toBe('6h')
    expect(formatAge(ago(12 * 86_400_000), now)).toBe('12d')
    expect(formatAge(ago(2 * 365 * 86_400_000), now)).toBe('2y')
  })

  it('floors rather than rounds, so 47 hours is one day', () => {
    expect(formatAge(ago(47 * 3_600_000), now)).toBe('1d')
  })

  it('reads an ISO string, which is how it arrives', () => {
    expect(formatAge('2026-08-06T14:22:00Z', now)).toBe('5d')
  })

  it('does not show a negative age when the clocks disagree', () => {
    expect(formatAge(ago(-60_000), now)).toBe('now')
  })

  it('says so when the date is unreadable', () => {
    expect(formatAge('not a date', now)).toBe('?')
  })
})

describe('formatClock', () => {
  it('is twenty-four hour and zero padded', () => {
    const at = new Date(2026, 7, 11, 9, 5)
    expect(formatClock(at)).toBe('09:05')
  })

  it('says so when the date is unreadable', () => {
    expect(formatClock('not a date')).toBe('?')
  })
})

describe('formatWhen', () => {
  const now = new Date(2026, 7, 11, 18, 0)

  it('gives the clock for something that happened today', () => {
    expect(formatWhen(new Date(2026, 7, 11, 14, 22), now)).toBe('14:22')
  })

  it('gives the age for anything older, since a bare time would mislead', () => {
    expect(formatWhen(new Date(2026, 7, 8, 14, 22), now)).toBe('3d')
  })
})
