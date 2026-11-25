import { useLiveQuery } from 'dexie-react-hooks'
import { useEffect, useState } from 'react'
import { catalogHealth, getCatalogMeta, type CatalogHealth } from './catalog'
import { useConnection } from './connection'
import { db, type QueuedSale } from './db'

export interface OfflineSummary {
  online: boolean
  queue: QueuedSale[]
  pending: number // saved here, not yet sent
  needsAttention: number // conflicts and failures
  health: CatalogHealth
  catalogHoursOld: number | null
}

/** Live view of the device's offline state, for the connection badge and the POS. */
export function useOfflineSummary(storeId: string): OfflineSummary {
  const online = useConnection((s) => s.online)
  const queue = useLiveQuery(
    () => db.queue.orderBy('soldAt').reverse().toArray(),
    [],
    [] as QueuedSale[],
  )
  const meta = useLiveQuery(() => getCatalogMeta(), [])
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 60_000)
    return () => clearInterval(t)
  }, [])
  return {
    online,
    queue,
    pending: queue.filter((s) => s.status === 'pending' || s.status === 'syncing').length,
    needsAttention: queue.filter((s) => s.status === 'conflict' || s.status === 'failed').length,
    health: catalogHealth(meta, storeId, now),
    catalogHoursOld: meta ? (now - meta.fetchedAt) / 3_600_000 : null,
  }
}
