import type { ReactNode } from 'react'

interface Props {
  title: string
  children: ReactNode
}

/**
 * The one panel shape both overlays use.
 *
 * Nothing animates it in. The motion budget is near zero, and an overlay that
 * a key opened does not need to explain where it came from.
 */
export function Overlay({ title, children }: Props) {
  return (
    <div className="fixed inset-0 z-10 flex items-start justify-center pt-[12vh]">
      <div className="absolute inset-0 bg-bg opacity-80" />
      <div className="relative max-h-[80vh] w-[560px] max-w-[92vw] overflow-hidden border border-line-strong bg-surface">
        <div className="border-b border-line px-[14px] py-[9px] text-xs tracking-brand text-fg-dimmer">
          {title}
        </div>
        {children}
      </div>
    </div>
  )
}
