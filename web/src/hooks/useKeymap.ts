import { useEffect, useRef } from 'react'

/**
 * One key, what it does, and how to say so in the help sheet.
 *
 * The help sheet is built from the same array the handler reads, so a key that
 * works and is not documented cannot exist.
 */
export interface Binding {
  /** As `describe` writes it: `j`, `G`, `Enter`, `space`, `?`, `mod+k`. */
  key: string
  label: string
  group: string
  run: () => void
  /** Allowed while a text field has focus. Escape needs it; little else does. */
  inFields?: boolean
  /** Whether holding the key repeats it. Off unless the action is safe held. */
  repeats?: boolean
  /** Left out of the help sheet, for a key that is only an alias. */
  hidden?: boolean
}

/** How a key press is named, so a binding can be written the way it is read. */
export function describe(event: KeyboardEvent): string {
  const key = event.key === ' ' ? 'space' : event.key
  // One name for both, because the same hand does the same thing on either
  // platform and nothing here needs to tell them apart.
  return event.metaKey || event.ctrlKey ? `mod+${key}` : key
}

/** Whether the press belongs to something being typed into. */
function inTextField(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  return ['input', 'textarea', 'select'].includes(target.tagName.toLowerCase())
}

/**
 * The keymap, registered once on the document.
 *
 * Once, not per component: the keyboard is the primary input here and it has
 * to behave the same wherever the last click landed. The bindings themselves
 * are read through a ref, so changing what a key does does not cost a listener
 * being torn down and put back on every render.
 */
export function useKeymap(bindings: Binding[]): void {
  const latest = useRef(bindings)

  useEffect(() => {
    latest.current = bindings
  }, [bindings])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const combo = describe(event)
      const binding = latest.current.find((candidate) => candidate.key === combo)
      if (!binding) return
      if (inTextField(event.target) && !binding.inFields) return
      // A leaned-on key repeats only where the action is meant to be held.
      if (event.repeat && !binding.repeats) return
      event.preventDefault()
      binding.run()
    }

    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [])
}
