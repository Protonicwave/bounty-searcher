import { useEffect, useRef, useState } from 'react'

import { Overlay } from './Overlay'

export interface Command {
  id: string
  label: string
  group: string
  run: () => void
}

/** Plain substring matching. A palette of twenty entries needs nothing more. */
function matching(commands: Command[], term: string): Command[] {
  const needle = term.trim().toLowerCase()
  if (needle === '') return commands
  return commands.filter((command) =>
    `${command.group} ${command.label}`.toLowerCase().includes(needle),
  )
}

interface Props {
  commands: Command[]
  onClose: () => void
}

/**
 * Everything the keyboard cannot reach directly: views, ordering, filters, and
 * starting a sweep.
 *
 * It handles its own keys on the input rather than through the global keymap,
 * because while it is open it is the only thing the keyboard is talking to.
 */
export function CommandPalette({ commands, onClose }: Props) {
  const [term, setTerm] = useState('')
  const [at, setAt] = useState(0)
  const chosen = useRef<HTMLDivElement>(null)

  const found = matching(commands, term)
  const index = Math.min(at, Math.max(0, found.length - 1))

  useEffect(() => {
    chosen.current?.scrollIntoView({ block: 'nearest' })
  }, [index])

  return (
    <Overlay title="COMMAND">
      <input
        autoFocus
        value={term}
        placeholder="what do you want to do"
        onChange={(event) => {
          setTerm(event.target.value)
          setAt(0)
        }}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown' || (event.key === 'n' && event.ctrlKey)) {
            event.preventDefault()
            setAt(Math.min(index + 1, found.length - 1))
          } else if (event.key === 'ArrowUp' || (event.key === 'p' && event.ctrlKey)) {
            event.preventDefault()
            setAt(Math.max(index - 1, 0))
          } else if (event.key === 'Enter') {
            event.preventDefault()
            found[index]?.run()
            onClose()
          } else if (event.key === 'Escape') {
            event.preventDefault()
            onClose()
          }
        }}
        className="w-full border-b border-line bg-transparent px-[14px] py-[10px] text-base text-fg outline-none placeholder:text-fg-ghost"
      />
      <div className="scrollbar-thin max-h-[46vh] overflow-y-auto py-[4px]">
        {found.length === 0 ? (
          <div className="px-[14px] py-[8px] text-xs text-fg-dimmer">
            Nothing by that name.
          </div>
        ) : (
          found.map((command, i) => (
            <div
              key={command.id}
              ref={i === index ? chosen : null}
              onMouseDown={() => {
                command.run()
                onClose()
              }}
              className={`flex items-baseline justify-between gap-[12px] px-[14px] py-[5px] text-xs ${
                i === index ? 'bg-accent-bg text-fg' : 'text-fg-dim'
              }`}
            >
              <span>{command.label}</span>
              <span className="text-fg-ghost">{command.group}</span>
            </div>
          ))
        )}
      </div>
    </Overlay>
  )
}
