/**
 * The one place that talks to the API.
 *
 * Requests go to a relative path because the interface is served from the same
 * origin in production and proxied to it in development, so there is no base
 * URL to configure and no cross-origin request to arrange.
 */

import type { Filters } from './filters'
import type {
  BountyDetail,
  BountyPage,
  Meta,
  ScanStarted,
  SortKey,
  TriageResult,
  TriageStatus,
  UndoResult,
  ViewName,
} from './types'

const PREFIX = '/api'

/** A response the API refused. Carries the status so a caller can tell 404 from 500. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

/** FastAPI reports a refusal as `detail`, which is either a string or a list. */
async function reason(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json()
    if (body !== null && typeof body === 'object' && 'detail' in body) {
      const detail: unknown = body.detail
      if (typeof detail === 'string') return detail
      return JSON.stringify(detail)
    }
  } catch {
    // A body that is not JSON tells us nothing the status has not already.
  }
  return response.statusText || `HTTP ${String(response.status)}`
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${PREFIX}${path}`, {
    headers: { accept: 'application/json' },
    ...(signal ? { signal } : {}),
  })
  if (!response.ok) {
    throw new ApiError(response.status, await reason(response))
  }
  return (await response.json()) as T
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${PREFIX}${path}`, {
    method: 'POST',
    headers: { accept: 'application/json', 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    throw new ApiError(response.status, await reason(response))
  }
  return (await response.json()) as T
}

/**
 * Which slice of the corpus is on screen: a saved view, the chips layered over
 * it, and how it is ordered. A null sort means the view's own answer.
 */
export interface BountyQuery {
  view: ViewName
  sort: SortKey | null
  filters: Filters
}

/**
 * The query as the API reads it.
 *
 * An absent parameter means "leave the view's own answer alone", so a filter
 * that is not set is omitted rather than sent empty. Exported because the query
 * key is built from the same object and the two must not drift.
 */
export function searchParams(query: BountyQuery): URLSearchParams {
  const params = new URLSearchParams({ view: query.view })
  const f = query.filters
  if (query.sort) params.set('sort', query.sort)
  if (f.q) params.set('q', f.q)
  if (f.language) params.set('language', f.language)
  if (f.minAmountMinor !== undefined) {
    params.set('min_amount_minor', String(f.minAmountMinor))
  }
  if (f.minStars !== undefined) params.set('min_stars', String(f.minStars))
  if (f.maxAgeDays !== undefined) params.set('max_age_days', String(f.maxAgeDays))
  if (f.minScore !== undefined) params.set('min_score', String(f.minScore))
  if (f.includeSuspect !== undefined) {
    params.set('include_suspect', String(f.includeSuspect))
  }
  if (f.includeClaimed !== undefined) {
    params.set('include_claimed', String(f.includeClaimed))
  }
  // Repeated rather than joined: the API declares it as a list parameter.
  for (const status of f.statuses ?? []) params.append('statuses', status)
  return params
}

export const api = {
  /** Corpus counts, the saved views, the quota and the last scan, in one call. */
  meta: (signal?: AbortSignal): Promise<Meta> => get<Meta>('/meta', signal),

  /** One page of the corpus. A null cursor asks for the first. */
  bounties: (
    query: BountyQuery,
    cursor: string | null,
    signal?: AbortSignal,
  ): Promise<BountyPage> => {
    const params = searchParams(query)
    if (cursor) params.set('cursor', cursor)
    return get<BountyPage>(`/bounties?${params.toString()}`, signal)
  },

  /** One bounty in full: body, breakdown, and where the figure came from. */
  bounty: (id: number, signal?: AbortSignal): Promise<BountyDetail> =>
    get<BountyDetail>(`/bounties/${String(id)}`, signal),

  /** Move rows to a status. Several ids under one call share one undo token. */
  triage: (
    bountyIds: number[],
    status: TriageStatus,
    snoozeUntil?: string,
  ): Promise<TriageResult> =>
    post<TriageResult>('/triage', {
      bounty_ids: bountyIds,
      status,
      ...(snoozeUntil ? { snooze_until: snoozeUntil } : {}),
    }),

  /** Reverse a transition, or the most recent one when no token is given. */
  undo: (undoToken?: string): Promise<UndoResult> =>
    post<UndoResult>('/triage/undo', { undo_token: undoToken ?? null }),

  /** Begin a sweep in the background. Returns once the run has an identity. */
  startScan: (): Promise<ScanStarted> => post<ScanStarted>('/scan', {}),
}
