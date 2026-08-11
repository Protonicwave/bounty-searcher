// @vitest-environment jsdom

import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useKeymap, type Binding } from './useKeymap'

afterEach(cleanup)

function Harness({ bindings }: { bindings: Binding[] }) {
  useKeymap(bindings)
  return <input data-testid="field" />
}

function press(init: KeyboardEventInit & { key: string }, target?: Element) {
  const event = new KeyboardEvent('keydown', { bubbles: true, ...init })
  ;(target ?? document.body).dispatchEvent(event)
  return event
}

describe('useKeymap', () => {
  it('runs the binding whose key was pressed, and no other', () => {
    const j = vi.fn()
    const k = vi.fn()
    render(
      <Harness
        bindings={[
          { key: 'j', label: 'down', group: 'move', run: j },
          { key: 'k', label: 'up', group: 'move', run: k },
        ]}
      />,
    )
    press({ key: 'j' })
    expect(j).toHaveBeenCalledTimes(1)
    expect(k).not.toHaveBeenCalled()
  })

  it('keeps its hands off while something is being typed into', () => {
    const run = vi.fn()
    const { getByTestId } = render(
      <Harness bindings={[{ key: 'j', label: 'down', group: 'move', run }]} />,
    )
    press({ key: 'j' }, getByTestId('field'))
    expect(run).not.toHaveBeenCalled()
  })

  it('lets a binding that asks for it through a text field anyway', () => {
    const run = vi.fn()
    const { getByTestId } = render(
      <Harness
        bindings={[
          { key: 'Escape', label: 'clear', group: 'find', inFields: true, run },
        ]}
      />,
    )
    press({ key: 'Escape' }, getByTestId('field'))
    expect(run).toHaveBeenCalledTimes(1)
  })

  it('ignores a held key unless the action is meant to be held', () => {
    const held = vi.fn()
    const once = vi.fn()
    render(
      <Harness
        bindings={[
          { key: 'j', label: 'down', group: 'move', repeats: true, run: held },
          { key: 'x', label: 'dismiss', group: 'do', run: once },
        ]}
      />,
    )
    press({ key: 'j', repeat: true })
    press({ key: 'x', repeat: true })
    expect(held).toHaveBeenCalledTimes(1)
    expect(once).not.toHaveBeenCalled()
  })

  it('reads either modifier as the same one, so both platforms agree', () => {
    const run = vi.fn()
    render(
      <Harness bindings={[{ key: 'mod+k', label: 'palette', group: 'find', run }]} />,
    )
    press({ key: 'k', ctrlKey: true })
    press({ key: 'k', metaKey: true })
    expect(run).toHaveBeenCalledTimes(2)
  })

  it('leaves a key nothing is bound to alone', () => {
    render(<Harness bindings={[]} />)
    expect(press({ key: 'q' }).defaultPrevented).toBe(false)
  })

  it('picks up a rebound action without re-registering the listener', () => {
    const first = vi.fn()
    const second = vi.fn()
    const { rerender } = render(
      <Harness bindings={[{ key: 'j', label: 'down', group: 'move', run: first }]} />,
    )
    rerender(
      <Harness bindings={[{ key: 'j', label: 'down', group: 'move', run: second }]} />,
    )
    press({ key: 'j' })
    expect(first).not.toHaveBeenCalled()
    expect(second).toHaveBeenCalledTimes(1)
  })
})
