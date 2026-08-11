import { describe, expect, it } from 'vitest'

import { activeChips, withoutFilter } from './filters'

describe('activeChips', () => {
  it('shows nothing when nothing is narrowing the corpus', () => {
    expect(activeChips({})).toEqual([])
  })

  it('labels a money floor as money', () => {
    expect(activeChips({ minAmountMinor: 10_000 })).toEqual([
      { key: 'minAmountMinor', label: '$100+' },
    ])
  })

  it('says unclaimed rather than naming the parameter', () => {
    expect(activeChips({ includeClaimed: false })).toEqual([
      { key: 'includeClaimed', label: 'unclaimed' },
    ])
  })

  it('treats a false suspect filter as active, since it is not the default', () => {
    expect(activeChips({ includeSuspect: true })[0]?.label).toBe('with suspect')
    expect(activeChips({ includeSuspect: false })[0]?.label).toBe('no suspect')
  })

  it('keeps a fixed order however the filters were set', () => {
    const keys = activeChips({
      includeClaimed: false,
      minStars: 1_400,
      language: 'typescript',
      q: 'cursor',
    }).map((chip) => chip.key)
    expect(keys).toEqual(['q', 'language', 'minStars', 'includeClaimed'])
  })

  it('ignores an empty status list, which narrows nothing', () => {
    expect(activeChips({ statuses: [] })).toEqual([])
  })

  it('ignores an empty search, which is the same as no search', () => {
    expect(activeChips({ q: '' })).toEqual([])
  })

  it('keeps a zero floor, because zero is a decision', () => {
    expect(activeChips({ minStars: 0 })).toEqual([
      { key: 'minStars', label: '0+ stars' },
    ])
  })
})

describe('withoutFilter', () => {
  it('drops one and leaves the rest', () => {
    expect(withoutFilter({ language: 'rust', minStars: 10 }, 'minStars')).toEqual({
      language: 'rust',
    })
  })

  it('does not mutate what it was given', () => {
    const filters = { language: 'rust' }
    withoutFilter(filters, 'language')
    expect(filters).toEqual({ language: 'rust' })
  })
})
