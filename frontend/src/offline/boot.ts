import { useEffect } from 'react'
import { registerSW } from 'virtual:pwa-register'
import { useActiveStore } from '@/lib/useActiveStore'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'
import { getCatalogMeta, refreshCatalog } from './catalog'
import { startConnectionMonitor, useConnection } from './connection'
import { ensureDevice } from './device'
import { startSyncLoop } from './syncEngine'

const REFRESH_EVERY_MS = 10 * 60_000

/** Call once, at startup. */
export function startOffline() {
  startConnectionMonitor()
  if (import.meta.env.PROD) {
    // The service worker keeps the app itself available with no connection. A new version waits
    // for the user to choose to reload, so an update can never interrupt a sale.
    const update = registerSW({
      onNeedRefresh: () => useUiStore.getState().setApplyUpdate(() => void update(true)),
    })
  }
  // When the connection comes back, an offline session becomes a real one.
  useConnection.subscribe((s, prev) => {
    if (s.online && !prev.online) void useAuthStore.getState().resume()
  })
}

/**
 * Keeps a till ready for the connection to drop: registers the device, keeps a fresh copy of the
 * catalogue, and sends queued sales whenever it can. Only for people who can make sales.
 */
export function useOfflineReadiness() {
  const canSell = useAuthStore((s) => s.can('sale:create'))
  const { storeId } = useActiveStore()

  useEffect(() => {
    if (!canSell || !storeId) return
    const refresh = async () => {
      if (!useConnection.getState().online) return
      try {
        const deviceId = await ensureDevice(storeId)
        const meta = await getCatalogMeta()
        const age = meta && meta.storeId === storeId ? Date.now() - meta.fetchedAt : Infinity
        if (age > 60_000) await refreshCatalog(storeId, deviceId)
      } catch {
        /* offline or signed out: the next attempt will do it */
      }
    }
    void refresh()
    const timer = setInterval(refresh, REFRESH_EVERY_MS)
    const unsubscribe = useConnection.subscribe((s, prev) => {
      if (s.online && !prev.online) void refresh()
    })
    const stopSync = startSyncLoop()
    return () => {
      clearInterval(timer)
      unsubscribe()
      stopSync()
    }
  }, [canSell, storeId])
}
