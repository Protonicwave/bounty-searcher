import { useEffect, useState } from 'react'

/** Long enough that a typed word is one query, short enough to feel like none. */
const SETTLE_MS = 150

interface Props {
  initial: string
  onCommit: (term: string) => void
}

/**
 * Text search, in the status line, where the chips are.
 *
 * There is no search bar until you ask for one, because the status line is the
 * only chrome the interface has and a field sitting in it empty all evening
 * would be the largest thing on screen that does nothing.
 *
 * The corpus is local, so this could run on every keystroke. It settles first
 * anyway: a request per character would still put the list through a full
 * re-key for a word you have not finished typing.
 */
export function SearchField({ initial, onCommit }: Props) {
  const [draft, setDraft] = useState(initial)

  useEffect(() => {
    const id = setTimeout(() => {
      onCommit(draft)
    }, SETTLE_MS)
    return () => {
      clearTimeout(id)
    }
  }, [draft, onCommit])

  return (
    <input
      autoFocus
      value={draft}
      placeholder="search titles and repositories"
      onChange={(event) => {
        setDraft(event.target.value)
      }}
      className="w-[280px] border border-line bg-transparent px-[6px] py-px text-xs text-fg outline-none placeholder:text-fg-ghost"
    />
  )
}
