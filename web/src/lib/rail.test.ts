import { describe, expect, it } from 'vitest'

import { breakdownSpan, breakdownWidth, railSegments } from './rail'
import type { Component, ScoreComponent } from './types'

function parts(
  values: Partial<Record<ScoreComponent, [number, number]>>,
): Component[] {
  const order: ScoreComponent[] = [
    'payout',
    'language',
    'effort',
    'freshness',
    'competition',
    'repository',
  ]
  return order.map((component) => {
    const [value, maximum] = values[component] ?? [0, 0]
    return { component, value, maximum }
  })
}

const total = (segments: { width: number }[]) =>
  segments.reduce((sum, s) => sum + s.width, 0)

describe('railSegments', () => {
  it('fills exactly as much of the rail as the score', () => {
    const segments = railSegments(82, parts({ payout: [22, 40], language: [18, 15] }))
    expect(total(segments)).toBeCloseTo(82)
  })

  it('shares the filled length out in proportion to what was earned', () => {
    const segments = railSegments(60, parts({ payout: [30, 40], freshness: [10, 12] }))
    const payout = segments.find((s) => s.component === 'payout')
    const freshness = segments.find((s) => s.component === 'freshness')
    expect(payout?.width).toBeCloseTo(45)
    expect(freshness?.width).toBeCloseTo(15)
  })

  it('keeps the order the API sent, so a column reads down consistently', () => {
    const segments = railSegments(50, parts({ payout: [10, 40] }))
    expect(segments.map((s) => s.component)).toEqual([
      'payout',
      'language',
      'effort',
      'freshness',
      'competition',
      'repository',
    ])
  })

  it('gives a penalty no length, since a rail cannot run backwards', () => {
    const segments = railSegments(
      40,
      parts({ payout: [20, 40], competition: [-15, 0] }),
    )
    expect(segments.find((s) => s.component === 'competition')?.width).toBe(0)
    expect(total(segments)).toBeCloseTo(40)
  })

  it('draws nothing when no component earned anything', () => {
    // The base score is not a component, so a row carried entirely by it has
    // an empty rail. That is the honest reading rather than a missing one.
    const segments = railSegments(30, parts({ competition: [-4, 0] }))
    expect(total(segments)).toBe(0)
  })

  it('clamps a score outside the scale rather than overflowing the rail', () => {
    expect(total(railSegments(140, parts({ payout: [90, 40] })))).toBeCloseTo(100)
    expect(total(railSegments(-10, parts({ payout: [5, 40] })))).toBe(0)
  })
})

describe('breakdownSpan', () => {
  it('is the largest magnitude on show, earned or lost', () => {
    expect(breakdownSpan(parts({ payout: [12, 40], competition: [-45, 0] }))).toBe(45)
  })

  it('takes a maximum nothing reached, so an empty bar reads as empty', () => {
    expect(breakdownSpan(parts({ payout: [0, 40] }))).toBe(40)
  })
})

describe('breakdownWidth', () => {
  it('measures every bar against the one shared span', () => {
    expect(breakdownWidth(20, 40)).toBe(50)
    expect(breakdownWidth(-40, 40)).toBe(100)
  })

  it('has nothing to divide by when there is no span', () => {
    expect(breakdownWidth(0, 0)).toBe(0)
  })
})
