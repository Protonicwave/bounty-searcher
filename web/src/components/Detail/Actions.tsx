/**
 * What can be done to the bounty on screen, and the key that does it.
 *
 * The keyboard is the primary input, so these read as a legend rather than as
 * a toolbar. They are still buttons: the mouse is a fallback, and a fallback
 * that only names the answer is not one.
 */

export interface Action {
  label: string
  /** The key that does the same thing, which is how it is normally done. */
  hint: string
  onClick: () => void
  primary?: boolean
}

export function Actions({ actions }: { actions: Action[] }) {
  return (
    <div className="mt-[22px] flex flex-wrap gap-[8px]">
      {actions.map((action) => (
        <button
          key={action.hint}
          type="button"
          onClick={action.onClick}
          className={`flex cursor-default items-center gap-[8px] border px-[9px] py-[5px] text-xs ${
            action.primary ? 'border-line-strong text-fg' : 'border-line text-fg-dim'
          }`}
        >
          {action.label}
          <span className="text-fg-ghost">{action.hint}</span>
        </button>
      ))}
    </div>
  )
}
