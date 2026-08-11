import {
  breakdownSpan,
  breakdownWidth,
  COMPONENT_COLOUR,
  COMPONENT_LABEL,
} from '@/lib/rail'
import type { Component } from '@/lib/types'

/** The scale the total is quoted against, which scoring clamps to. */
const OUT_OF = 100

interface Props {
  total: number
  components: Component[]
}

function signed(value: number): string {
  const rounded = Math.round(value)
  return rounded < 0 ? String(rounded) : `+${String(rounded)}`
}

/**
 * The score, and everything that made it, permanently visible.
 *
 * This is the premise of the tool, so it does not hide behind a disclosure
 * triangle. A penalty is drawn in the neutral rather than in its component's
 * colour, because a bar that looks earned and is not is worse than no bar.
 */
export function ScoreBreakdown({ total, components }: Props) {
  const span = breakdownSpan(components)

  return (
    <>
      <div className="mb-[12px] text-xs tracking-brand text-fg-dimmer">SCORE</div>
      <div className="mb-[14px] flex items-baseline gap-[10px]">
        <span className="text-3xl text-fg">{Math.round(total)}</span>
        <span className="text-xs text-fg-dimmer">of {OUT_OF}</span>
      </div>
      <div className="grid gap-[7px]">
        {components.map((part) => (
          <div
            key={part.component}
            className="grid grid-cols-[84px_minmax(0,1fr)_30px] items-center gap-[10px] text-xs"
          >
            <span className="text-fg-dim">{COMPONENT_LABEL[part.component]}</span>
            <span className="block h-[5px] bg-line">
              <span
                className="block h-full"
                style={{
                  width: `${String(breakdownWidth(part.value, span))}%`,
                  background:
                    part.value < 0
                      ? 'var(--color-fg-ghost)'
                      : COMPONENT_COLOUR[part.component],
                }}
              />
            </span>
            <span className="text-right text-fg">{signed(part.value)}</span>
          </div>
        ))}
      </div>
    </>
  )
}
