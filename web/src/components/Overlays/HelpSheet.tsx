import type { Binding } from '@/hooks/useKeymap'

import { Overlay } from './Overlay'

/** How a binding is written where somebody reads it rather than presses it. */
function keyLabel(key: string): string {
  return key.replace('mod+', 'mod ')
}

/** The bindings in the order they were declared, gathered under their groups. */
function grouped(bindings: Binding[]): [string, Binding[]][] {
  const groups = new Map<string, Binding[]>()
  for (const binding of bindings) {
    if (binding.hidden) continue
    const found = groups.get(binding.group)
    if (found) found.push(binding)
    else groups.set(binding.group, [binding])
  }
  return [...groups]
}

/**
 * Every key there is, taken from the keymap itself.
 *
 * Built from the same array the handler reads, so a key that works and is not
 * documented cannot exist and neither can the reverse.
 */
export function HelpSheet({ bindings }: { bindings: Binding[] }) {
  return (
    <Overlay title="KEYS">
      <div className="scrollbar-thin max-h-[56vh] overflow-y-auto px-[14px] py-[12px]">
        {grouped(bindings).map(([group, keys]) => (
          <div key={group} className="mb-[14px]">
            <div className="mb-[6px] text-xs text-fg-dimmer">{group}</div>
            {keys.map((binding) => (
              <div
                key={binding.key}
                className="grid grid-cols-[72px_minmax(0,1fr)] gap-[10px] py-[2px] text-xs"
              >
                <span className="text-fg">{keyLabel(binding.key)}</span>
                <span className="text-fg-dim">{binding.label}</span>
              </div>
            ))}
          </div>
        ))}
        <div className="text-xs text-fg-dimmer">
          mod is ctrl, or cmd on a Mac. Keys do nothing while you are typing.
        </div>
      </div>
    </Overlay>
  )
}
