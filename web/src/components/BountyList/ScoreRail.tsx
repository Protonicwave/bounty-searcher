import { memo } from 'react'

import { COMPONENT_COLOUR, railSegments } from '@/lib/rail'
import type { Component } from '@/lib/types'

interface Props {
  total: number
  components: Component[]
}

/**
 * Six real rectangles, sharp, at precise widths.
 *
 * Never block characters: an ASCII bar is a picture of a bar. Read down the
 * column the rail gives the shape of the whole result set, which is why the
 * filled length is the score and the colours are what earned it.
 */
export const ScoreRail = memo(function ScoreRail({ total, components }: Props) {
  return (
    <span className="mt-[4px] flex h-[7px] overflow-hidden bg-line">
      {railSegments(total, components).map((segment) => (
        <i
          key={segment.component}
          className="block h-full"
          style={{
            width: `${String(segment.width)}%`,
            background: COMPONENT_COLOUR[segment.component],
          }}
        />
      ))}
    </span>
  )
})
