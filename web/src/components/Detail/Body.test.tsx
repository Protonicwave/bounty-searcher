// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { Body } from './Body'

afterEach(cleanup)

describe('Body', () => {
  it('marks the payout at the offsets it was read from', () => {
    const source = 'Bounty of $500 for a fix, not the $500 in the quote above.'
    const { container } = render(
      <Body source={source} range={{ start: 10, end: 14 }} />,
    )
    const marks = container.querySelectorAll('mark')
    expect(marks).toHaveLength(1)
    expect(marks[0]?.textContent).toBe('$500')
  })

  it('puts nothing in the markup that came out of the body', () => {
    const source = 'Try <img src=x onerror=alert(1)> and <b>this</b>.'
    const { container } = render(<Body source={source} range={null} />)
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('b')).toBeNull()
    expect(container.textContent).toContain('<img src=x onerror=alert(1)>')
  })

  it('refuses to link a scheme nobody should follow', () => {
    const { container } = render(
      <Body source={'[click](javascript:alert(1))'} range={null} />,
    )
    expect(container.querySelector('a')).toBeNull()
    expect(screen.getByText('click')).toBeDefined()
  })

  it('opens a real link away from the interface', () => {
    const { container } = render(
      <Body source={'[docs](https://example.com)'} range={null} />,
    )
    const link = container.querySelector('a')
    expect(link?.getAttribute('href')).toBe('https://example.com')
    expect(link?.getAttribute('rel')).toBe('noreferrer noopener')
  })

  it('says so plainly when there is nothing to read', () => {
    render(<Body source={''} range={null} />)
    expect(screen.getByText('No description.')).toBeDefined()
  })
})
