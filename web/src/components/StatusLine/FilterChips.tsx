import { activeChips, type FilterKey, type Filters } from '@/lib/filters'

interface Props {
  filters: Filters
  onRemove: (key: FilterKey) => void
}

/**
 * The active filters, and the only way to see them.
 *
 * There is no sidebar, so a filter that is on is visible here or it is
 * invisible. Nothing renders when nothing is narrowing the corpus.
 */
export function FilterChips({ filters, onRemove }: Props) {
  return activeChips(filters).map((chip) => (
    <button
      key={chip.key}
      type="button"
      title={`Remove ${chip.label}`}
      onClick={() => {
        onRemove(chip.key)
      }}
      className="cursor-default border border-line px-[6px] py-px text-fg"
    >
      {chip.label}
      <span className="ml-[5px] text-fg-dimmer">x</span>
    </button>
  ))
}
