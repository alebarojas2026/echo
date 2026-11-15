import type { FeedSnapshot } from '../room/feed'

/** Board epoch time, advanced only by the browser's monotonic clock since that state arrived. */
export function boardNow(snapshot: Pick<FeedSnapshot, 'state' | 'receivedAt'> | null, now = performance.now()): number | null {
  const t = snapshot?.state?.t, arrived = snapshot?.receivedAt
  if (typeof t !== 'number' || !Number.isFinite(t) || t < 0 || typeof arrived !== 'number' || !Number.isFinite(arrived)) return null
  return Math.floor(t + Math.max(0, now - arrived))
}
