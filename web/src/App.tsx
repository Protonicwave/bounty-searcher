import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { BountyList, Quiet } from '@/components/BountyList'
import { Detail } from '@/components/Detail'
import { CommandPalette, HelpSheet } from '@/components/Overlays'
import { StatusLine } from '@/components/StatusLine'
import { UndoNotice } from '@/components/UndoNotice'
import { useBounties } from '@/hooks/useBounties'
import { useKeymap, type Binding } from '@/hooks/useKeymap'
import { useMeta } from '@/hooks/useMeta'
import { useNow } from '@/hooks/useNow'
import { useTriage } from '@/hooks/useTriage'
import { api, type BountyQuery } from '@/lib/api'
import { buildCommands, VIEW_ORDER } from '@/lib/commands'
import { withoutFilter, type FilterKey, type Filters } from '@/lib/filters'
import { cloneCommand } from '@/lib/github'
import { keys } from '@/lib/keys'
import type { BountyRow, SortKey, TriageStatus, ViewName } from '@/lib/types'

/** One array identity for every empty list, so nothing re-renders on nothing. */
const NO_ROWS: BountyRow[] = []

/** How long the copy action says it worked before going back to offering it. */
const CONFIRM_MS = 1_500

type OverlayName = 'help' | 'command'

/**
 * The shell: a status line that never moves, and two panes under it.
 *
 * Sixty to forty. The list needs the width for titles and the detail pane
 * needs a measure rather than a column, so widening it past forty would make
 * the prose worse, not better.
 *
 * Every piece of state a key can reach lives here, because the keymap is
 * registered once on the document and has to be able to reach all of it.
 */
export function App() {
  const client = useQueryClient()
  const meta = useMeta()
  const nowMs = useNow()

  const [view, setView] = useState<ViewName>('tonight')
  const [sort, setSort] = useState<SortKey | null>(null)
  const [filters, setFilters] = useState<Filters>({})
  const query: BountyQuery = useMemo(
    () => ({ view, sort, filters }),
    [view, sort, filters],
  )

  // Held still rather than rebuilt, since an optimistic edit is aimed at it.
  const listKey = useMemo(() => keys.list(query), [query])
  const listing = useBounties(query)
  const rows = listing.data?.rows ?? NO_ROWS
  const [selected, setSelected] = useState(0)
  const [expanded, setExpanded] = useState(false)
  const [searching, setSearching] = useState(false)
  const [overlay, setOverlay] = useState<OverlayName | null>(null)
  const [copied, setCopied] = useState(false)
  const [restoring, setRestoring] = useState<number | null>(null)

  // A different question deserves its first answer, not the position you held
  // in the last one.
  useEffect(() => {
    setSelected(0)
  }, [query])

  // Rows leave under a dismissal, and the selection cannot follow them out.
  useEffect(() => {
    setSelected((at) => Math.max(0, Math.min(at, rows.length - 1)))
  }, [rows.length])

  // An undo puts a row back, and the selection goes back to it. It may take a
  // refetch to arrive, so this waits for it rather than guessing where it went.
  useEffect(() => {
    if (restoring === null) return
    const at = rows.findIndex((row) => row.id === restoring)
    if (at !== -1) {
      setSelected(at)
      setRestoring(null)
    }
  }, [restoring, rows])

  useEffect(() => {
    if (!copied) return
    const id = setTimeout(() => {
      setCopied(false)
    }, CONFIRM_MS)
    return () => {
      clearTimeout(id)
    }
  }, [copied])

  const current = rows[selected]
  const last = rows.length - 1

  const move = useCallback(
    (delta: number) => {
      setSelected((at) => Math.max(0, Math.min(at + delta, last)))
    },
    [last],
  )

  const openOnGitHub = useCallback(() => {
    // Opening does not move the selection, so several can be queued from the
    // keyboard without going back to the list between them.
    if (current) window.open(current.url, '_blank', 'noopener')
  }, [current])

  const copyClone = useCallback(() => {
    if (!current) return
    void navigator.clipboard.writeText(cloneCommand(current))
    setCopied(true)
  }, [current])

  const search = useCallback((term: string) => {
    setFilters((held) => {
      // The same term is not a new question, so the list is left where it is.
      if ((held.q ?? '') === term) return held
      return term === '' ? withoutFilter(held, 'q') : { ...held, q: term }
    })
  }, [])

  const removeFilter = useCallback((key: FilterKey) => {
    setFilters((held) => withoutFilter(held, key))
  }, [])

  const { fetchNextPage } = listing
  const nextPage = useCallback(() => {
    void fetchNextPage()
  }, [fetchNextPage])

  const scan = useMutation({
    mutationFn: () => api.startScan(),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.meta })
    },
  })
  const startScan = useCallback(() => {
    scan.mutate()
  }, [scan])

  const { apply, undo, leaving, notice, dismissNotice } = useTriage({
    listKey,
    // Tonight is the one view defined by not having decided yet, so deciding
    // is what takes a row out of it. Anywhere else the row belongs either way.
    decidedLeaves: view === 'tonight' || (filters.statuses?.length ?? 0) > 0,
    onRestore: (ids) => {
      setRestoring(ids[0] ?? null)
    },
  })

  const decide = useCallback(
    (status: TriageStatus) => {
      if (current) apply(current.id, status)
    },
    [current, apply],
  )
  const shortlist = useCallback(() => {
    decide('shortlisted')
  }, [decide])
  const dismiss = useCallback(() => {
    decide('dismissed')
  }, [decide])

  const commands = useMemo(
    () =>
      buildCommands({
        views: meta.data?.views,
        filters,
        setView,
        setSort,
        setFilters,
        startScan,
        scanning: meta.data?.last_scan?.running ?? false,
      }),
    [meta.data, filters, startScan],
  )

  /** What the keys do, and the only description of them there is. */
  const bindings: Binding[] = useMemo(
    () => [
      {
        key: 'j',
        label: 'next bounty',
        group: 'move',
        repeats: true,
        run: () => {
          move(1)
        },
      },
      {
        key: 'k',
        label: 'previous bounty',
        group: 'move',
        repeats: true,
        run: () => {
          move(-1)
        },
      },
      {
        key: 'g',
        label: 'first bounty',
        group: 'move',
        run: () => {
          setSelected(0)
        },
      },
      {
        key: 'G',
        label: 'last bounty loaded',
        group: 'move',
        run: () => {
          setSelected(Math.max(0, last))
        },
      },
      {
        key: 'Enter',
        label: 'open on GitHub, without leaving the list',
        group: 'do',
        run: openOnGitHub,
      },
      {
        key: 'space',
        label: 'give the issue the whole window',
        group: 'do',
        run: () => {
          setExpanded((wide) => !wide)
        },
      },
      { key: 'c', label: 'copy a clone command', group: 'do', run: copyClone },
      {
        key: 'x',
        label: 'dismiss, or hold to dismiss a run of them',
        group: 'decide',
        // Held on purpose: a run of dismissals is one decision and comes back
        // under one undo.
        repeats: true,
        run: dismiss,
      },
      { key: 's', label: 'shortlist', group: 'decide', run: shortlist },
      { key: 'u', label: 'undo the last decision', group: 'decide', run: undo },
      ...VIEW_ORDER.map((name, i) => ({
        key: String(i + 1),
        label:
          meta.data?.views.find((candidate) => candidate.name === name)?.title ?? name,
        group: 'view',
        run: () => {
          setView(name)
        },
      })),
      {
        key: '/',
        label: 'search titles and repositories',
        group: 'find',
        run: () => {
          setSearching(true)
        },
      },
      {
        key: 'Escape',
        label: 'clear the search',
        group: 'find',
        inFields: true,
        run: () => {
          setSearching(false)
          search('')
        },
      },
      {
        key: 'mod+k',
        label: 'everything else: ordering, filters, a sweep',
        group: 'find',
        run: () => {
          setOverlay('command')
        },
      },
      {
        key: '?',
        label: 'this sheet',
        group: 'find',
        run: () => {
          setOverlay('help')
        },
      },
    ],
    [
      move,
      last,
      openOnGitHub,
      copyClone,
      search,
      meta.data,
      dismiss,
      shortlist,
      undo,
    ],
  )

  /** While an overlay is up it is the only thing the keyboard is talking to. */
  const closing: Binding[] = useMemo(
    () => [
      {
        key: 'Escape',
        label: 'close',
        group: 'overlay',
        inFields: true,
        run: () => {
          setOverlay(null)
        },
      },
      {
        key: '?',
        label: 'close',
        group: 'overlay',
        run: () => {
          setOverlay(null)
        },
      },
    ],
    [],
  )

  useKeymap(overlay === null ? bindings : closing)

  // Nothing to show, and nothing on its way: the quiet state, not a blank pane.
  const quiet = rows.length === 0 && !listing.isPending && !listing.isError

  return (
    <div className="flex h-full flex-col">
      <StatusLine
        meta={meta.data}
        total={listing.data?.total}
        view={view}
        loading={listing.isPending}
        failed={meta.isError || listing.isError}
        filters={filters}
        onRemoveFilter={removeFilter}
        searching={searching}
        onSearch={search}
      />
      <div
        className={`grid min-h-0 flex-1 ${
          expanded ? 'grid-cols-1' : 'grid-cols-[minmax(0,60fr)_minmax(0,40fr)]'
        }`}
      >
        {!expanded &&
          (quiet ? (
            <Quiet
              meta={meta.data}
              view={meta.data?.views.find((candidate) => candidate.name === view)}
              filtered={Object.keys(filters).length > 0}
              nowMs={nowMs}
              onScan={startScan}
              onShowEverything={() => {
                setView('all')
              }}
              onClearFilters={() => {
                setFilters({})
              }}
            />
          ) : (
            <BountyList
              rows={rows}
              selected={selected}
              onSelect={setSelected}
              nowMs={nowMs}
              leaving={leaving}
              hasNextPage={listing.hasNextPage}
              isFetchingNextPage={listing.isFetchingNextPage}
              fetchNextPage={nextPage}
            />
          ))}
        <Detail
          row={current}
          nowMs={nowMs}
          onOpen={openOnGitHub}
          onShortlist={shortlist}
          onDismiss={dismiss}
          onCopyClone={copyClone}
          copied={copied}
        />
      </div>
      <UndoNotice notice={notice} onUndo={undo} onClose={dismissNotice} />
      {overlay === 'help' && <HelpSheet bindings={bindings} />}
      {overlay === 'command' && (
        <CommandPalette
          commands={commands}
          onClose={() => {
            setOverlay(null)
          }}
        />
      )}
    </div>
  )
}
