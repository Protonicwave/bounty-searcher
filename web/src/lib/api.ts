/**
 * The one place that talks to the API.
 *
 * Requests go to a relative path because the interface is served from the same
 * origin in production and proxied to it in development, so there is no base
 * URL to configure and no cross-origin request to arrange.
 */

import type { Meta } from './types'

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

export const api = {
  /** Corpus counts, the saved views, the quota and the last scan, in one call. */
  meta: (signal?: AbortSignal): Promise<Meta> => get<Meta>('/meta', signal),
}
