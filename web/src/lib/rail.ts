/**
 * The score rail: six real rectangles whose total length is the score.
 *
 * Read as a column down the list it gives the shape of the whole result set
 * without a single number being read, which is the point of it. So the filled
 * length has to mean the score exactly, and the colours within it have to mean
 * what earned it.
 */

import type { Component, ScoreComponent } from './types'

/** Where each segment takes its colour. Tokens, never literal values. */
export const COMPONENT_COLOUR: Record<ScoreComponent, string> = {
  payout: 'var(--color-score-payout)',
  language: 'var(--color-score-language)',
  effort: 'var(--color-score-effort)',
  freshness: 'var(--color-score-freshness)',
  competition: 'var(--color-score-competition)',
  repository: 'var(--color-score-repository)',
}

/** How the components are named where a person reads them rather than a rail. */
export const COMPONENT_LABEL: Record<ScoreComponent, string> = {
  payout: 'payout',
  language: 'language fit',
  effort: 'effort',
  freshness: 'freshness',
  competition: 'competition',
  repository: 'repo size',
}

export interface Segment {
  component: ScoreComponent
  /** Width as a percentage of the whole rail. */
  width: number
}

/**
 * One segment per component, in the order the API sent them.
 *
 * Only what a component earned is drawn. A penalty has no length to give, and
 * a rail that drew one would have to run backwards from somewhere; the score
 * beside it already carries the cost, and the detail pane names it. So the
 * earnings share out the filled length, which is the score itself: a row that
 * scores 82 fills 82% of its rail whatever the mix.
 */
export function railSegments(total: number, components: Component[]): Segment[] {
  const fill = Math.max(0, Math.min(100, total))
  const earned = components.map((part) => Math.max(0, part.value))
  const sum = earned.reduce((a, b) => a + b, 0)
  return components.map((part, i) => ({
    component: part.component,
    // Nothing earned means nothing to draw, however the base score lands.
    width: sum > 0 ? ((earned[i] ?? 0) / sum) * fill : 0,
  }))
}

/**
 * How much of its own track one component's bar fills, in the breakdown.
 *
 * Every bar in a breakdown is measured against the same span, so the six read
 * against each other rather than each against a private scale. The span is the
 * largest thing on show, whether that is a component at its maximum or a
 * penalty larger than any of them.
 */
export function breakdownWidth(value: number, span: number): number {
  if (span <= 0) return 0
  return Math.min(100, (Math.abs(value) / span) * 100)
}

/** The span the breakdown bars share: the largest magnitude in play. */
export function breakdownSpan(components: Component[]): number {
  return components.reduce(
    (widest, part) => Math.max(widest, Math.abs(part.value), part.maximum),
    0,
  )
}
