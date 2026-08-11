// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { components, row } from '@/test/builders'

import { Row } from './Row'

afterEach(cleanup)

const NOW = Date.parse('2026-06-06T12:00:00Z')

function draw(over: Parameters<typeof row>[0] = {}, selected = false) {
  const onSelect = vi.fn()
  const { container } = render(
    <Row
      row={row(over)}
      index={3}
      selected={selected}
      nowMs={NOW}
      onSelect={onSelect}
    />,
  )
  return { container, onSelect }
}

describe('Row', () => {
  it('shows the score, the payout and where it came from', () => {
    draw()
    expect(screen.getByText('82')).toBeDefined()
    expect(screen.getByText('$500')).toBeDefined()
    expect(screen.getByText('owner/repo')).toBeDefined()
    expect(screen.getByText('1.4k')).toBeDefined()
    expect(screen.getByText('5d')).toBeDefined()
  })

  it('says nothing rather than nought when there is no figure', () => {
    draw({ amount: null })
    expect(screen.getByText('?')).toBeDefined()
  })

  it('strikes a payout nobody can believe, and names why', () => {
    const { container } = draw({ suspect_reason: '0 stars' })
    expect(screen.getByText('suspect: 0 stars')).toBeDefined()
    expect(container.querySelector('.line-through')).not.toBeNull()
  })

  it('demotes a claimed row by contrast rather than by colour', () => {
    const { container } = draw({ claim_reason: 'assigned' })
    expect(screen.getByText('claimed')).toBeDefined()
    // No red anywhere: demotion is subtraction, and the rail simply fades.
    expect(container.querySelector('.opacity-40')).not.toBeNull()
  })

  it('marks what arrived since the last scan without a badge', () => {
    const { container } = draw({ is_new: true })
    expect(container.querySelectorAll('.bg-accent')).toHaveLength(1)
  })

  it('carries the selection as a background and a gutter bar, and nothing else', () => {
    const plain = draw().container.querySelectorAll('.bg-accent')
    const chosen = draw({}, true).container.querySelectorAll('.bg-accent')
    expect(plain).toHaveLength(0)
    // The gutter, which is rendered either way so selecting cannot mount it.
    expect(chosen).toHaveLength(1)
    expect(draw({}, true).container.querySelector('.bg-accent-bg')).not.toBeNull()
  })

  it('reports which row was pressed, so the mouse still works', () => {
    const { container, onSelect } = draw()
    const element = container.firstElementChild
    element?.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    expect(onSelect).toHaveBeenCalledWith(3)
  })

  it('draws six segments whatever the score is made of', () => {
    const { container } = draw({
      score: {
        total: 40,
        base: 30,
        components: components({ competition: -12 }),
        weights_hash: 'abcd1234',
      },
    })
    expect(container.querySelectorAll('i')).toHaveLength(6)
  })
})
