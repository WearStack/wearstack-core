import { create } from 'zustand'
import { API_URL, setNetworkHandler } from '@/lib/api'

/**
 * Whether the server is reachable. `navigator.onLine` only says a network is attached (Wi-Fi
 * without internet still reads "online"), so every real request also reports in, and while we
 * believe we are offline a light probe checks for the way back.
 */
interface ConnectionState {
  online: boolean
  setOnline: (online: boolean) => void
}

export const useConnection = create<ConnectionState>((set) => ({
  // Assume online unless the browser says otherwise (some environments have no onLine flag).
  online:
    typeof navigator === 'undefined' || navigator.onLine === undefined ? true : navigator.onLine,
  setOnline: (online) => set({ online }),
}))

const PROBE_MS = 10_000
let probeTimer: ReturnType<typeof setTimeout> | null = null

async function probe(): Promise<boolean> {
  try {
    const ctl = new AbortController()
    const t = setTimeout(() => ctl.abort(), 4000)
    const res = await fetch(`${API_URL}/health`, { cache: 'no-store', signal: ctl.signal })
    clearTimeout(t)
    return res.ok
  } catch {
    return false
  }
}

function scheduleProbe() {
  if (probeTimer) return
  probeTimer = setTimeout(async () => {
    probeTimer = null
    if (await probe()) {
      useConnection.getState().setOnline(true)
    } else {
      scheduleProbe()
    }
  }, PROBE_MS)
}

export function reportReachable(reachable: boolean) {
  const { online, setOnline } = useConnection.getState()
  if (reachable !== online) setOnline(reachable)
  if (!reachable) scheduleProbe()
}

/** Wires the connection monitor to the API client and the browser's online/offline events. */
export function startConnectionMonitor() {
  setNetworkHandler(reportReachable)
  window.addEventListener('offline', () => reportReachable(false))
  window.addEventListener('online', async () => {
    // The browser says a network is back; confirm the server is actually reachable.
    reportReachable(await probe())
  })
}
