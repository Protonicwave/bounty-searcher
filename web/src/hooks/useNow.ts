import { useEffect, useState } from 'react'

/** How often the ages on screen are allowed to be wrong by, in milliseconds. */
const TICK = 60_000

/**
 * The current moment, held still between ticks.
 *
 * Rows are memoised, so anything they read has to be stable or they re-render
 * on every keystroke. Ages are counted in days and hours, so a minute of drift
 * is invisible and a shared value that moves once a minute is enough.
 */
export function useNow(interval: number = TICK): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => {
      setNow(Date.now())
    }, interval)
    return () => {
      clearInterval(id)
    }
  }, [interval])
  return now
}
