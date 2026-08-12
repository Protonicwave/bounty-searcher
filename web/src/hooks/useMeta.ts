import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'
import { keys } from '@/lib/keys'

/** How often to ask again while a sweep is running, in milliseconds. */
const WHILE_SCANNING = 2_000

/**
 * Everything the status line shows, in one request.
 *
 * Nothing in the corpus changes without a scan, so this sits still most of the
 * time. While a sweep is running it is polled, because the counts and the
 * quota move under it and there is no progress stream to read yet.
 */
export function useMeta() {
  return useQuery({
    queryKey: keys.meta,
    queryFn: ({ signal }) => api.meta(signal),
    staleTime: 10_000,
    refetchInterval: (query) =>
      query.state.data?.last_scan?.running ? WHILE_SCANNING : false,
  })
}
