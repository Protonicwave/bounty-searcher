import type { Notice } from '@/hooks/useTriage'

interface Props {
  notice: Notice | null
  onUndo: () => void
  onClose: () => void
}

/**
 * What just happened, and the offer to take it back.
 *
 * It sits over the detail pane rather than over the list. Moving down a list
 * keeps the selection at the bottom of it, which is exactly where a message in
 * the bottom corner would land, and covering the row you are deciding about is
 * worse than saying nothing at all.
 *
 * It says nothing until you have done something, and goes away on its own: a
 * decision is only worth reversing while you can still remember making it.
 */
export function UndoNotice({ notice, onUndo, onClose }: Props) {
  if (!notice) return null

  return (
    <div className="fixed right-[14px] bottom-[14px] flex items-center gap-[12px] border border-line-strong bg-surface px-[10px] py-[6px] text-xs text-fg-dim">
      <span className="text-fg">{notice.text}</span>
      {notice.token !== null && (
        <button
          type="button"
          onClick={onUndo}
          className="flex cursor-default items-center gap-[6px] text-fg-dim"
        >
          undo <span className="text-fg-ghost">u</span>
        </button>
      )}
      <button
        type="button"
        onClick={onClose}
        title="Dismiss this message"
        className="cursor-default text-fg-ghost"
      >
        x
      </button>
    </div>
  )
}
