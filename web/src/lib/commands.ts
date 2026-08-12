/**
 * What the command palette can do.
 *
 * Everything here is something the keyboard cannot reach directly: an ordering,
 * a threshold, a sweep. The four views have their own keys as well, and appear
 * here too because a palette that hides half the answers is a worse palette.
 */

import type { Command } from '@/components/Overlays'

import { formatCount, formatMoney } from './format'
import type { Filters } from './filters'
import type { SortKey, View, ViewName } from './types'

/** The currency the amount floor is quoted in. The wire carries no other. */
const FLOOR_CURRENCY = 'USD'

/** Thresholds worth one keystroke. Not policy: a filter you chose and can see. */
const AMOUNT_FLOORS = [10_000, 50_000, 100_000]
const STAR_FLOORS = [100, 1_000]

const SORTS: [SortKey, string][] = [
  ['score', 'best first'],
  ['payout', 'most money first'],
  ['newest', 'newest first'],
]

/** The views, in the order the number keys switch between them. */
export const VIEW_ORDER: ViewName[] = ['tonight', 'payday', 'changed', 'all']

interface Options {
  views: View[] | undefined
  filters: Filters
  setView: (view: ViewName) => void
  setSort: (sort: SortKey) => void
  setFilters: (next: (current: Filters) => Filters) => void
  startScan: () => void
  scanning: boolean
}

export function buildCommands({
  views,
  filters,
  setView,
  setSort,
  setFilters,
  startScan,
  scanning,
}: Options): Command[] {
  const named =
    views ?? VIEW_ORDER.map((name): View => ({ name, title: name, description: '' }))

  const commands: Command[] = named.map((view) => ({
    id: `view-${view.name}`,
    label: view.description ? `${view.title}: ${view.description}` : view.title,
    group: 'view',
    run: () => {
      setView(view.name)
    },
  }))

  for (const [sort, label] of SORTS) {
    commands.push({
      id: `sort-${sort}`,
      label: `Sort by ${label}`,
      group: 'order',
      run: () => {
        setSort(sort)
      },
    })
  }

  for (const floor of AMOUNT_FLOORS) {
    commands.push({
      id: `amount-${String(floor)}`,
      label: `Pays ${formatMoney(floor, FLOOR_CURRENCY)} or more`,
      group: 'filter',
      run: () => {
        setFilters((current) => ({ ...current, minAmountMinor: floor }))
      },
    })
  }

  for (const floor of STAR_FLOORS) {
    commands.push({
      id: `stars-${String(floor)}`,
      label: `${formatCount(floor)} stars or more`,
      group: 'filter',
      run: () => {
        setFilters((current) => ({ ...current, minStars: floor }))
      },
    })
  }

  commands.push(
    {
      id: 'claimed',
      label: filters.includeClaimed ? 'Hide claimed bounties' : 'Show claimed bounties',
      group: 'filter',
      run: () => {
        setFilters((current) => ({
          ...current,
          includeClaimed: !(current.includeClaimed ?? false),
        }))
      },
    },
    {
      id: 'suspect',
      label: filters.includeSuspect ? 'Hide suspect bounties' : 'Show suspect bounties',
      group: 'filter',
      run: () => {
        setFilters((current) => ({
          ...current,
          includeSuspect: !(current.includeSuspect ?? false),
        }))
      },
    },
    {
      id: 'clear',
      label: 'Clear every filter',
      group: 'filter',
      run: () => {
        setFilters(() => ({}))
      },
    },
    {
      id: 'scan',
      label: scanning ? 'A sweep is already running' : 'Scan for new bounties now',
      group: 'corpus',
      run: () => {
        if (!scanning) startScan()
      },
    },
  )

  return commands
}
