import { api, ApiError } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'
import { refreshCatalog, getCatalogMeta } from './catalog'
import { useConnection } from './connection'
import { db, type QueuedSale, type QueueStatus, type SyncOutcome } from './db'
import { ensureDevice, forgetDevice } from './device'
import { pruneSettled } from './queue'

export const BACKOFF_BASE_MS = 5_000
export const BACKOFF_MAX_MS = 300_000
const DEFAULT_BATCH = 20

interface ServerResult {
  operation_id: string
  client_operation_id: string
  status: 'received' | 'applied' | 'conflict' | 'failed' | 'rejected'
  sale_id: string | null
  invoice_number: string | null
  conflicts: Record<string, unknown>[]
  error_code: string | null
  error_message: string | null
}

export interface DrainSummary {
  sent: number
  applied: number
  held: number // conflicts, failures and rejections that now need a person
  deferred: boolean // nothing was attempted (offline, signed out, or nothing to send)
}

export const backoffMs = (attempts: number) =>
  Math.min(BACKOFF_MAX_MS, BACKOFF_BASE_MS * 2 ** Math.max(0, attempts - 1))

const payload = (s: QueuedSale) => ({
  client_operation_id: s.localId,
  store_id: s.storeId,
  sold_at: s.soldAt,
  cashier_id: s.cashierId,
  customer_id: s.customerId,
  provisional_number: s.provisionalNumber,
  items: s.items.map((i) => ({
    variant_id: i.variantId,
    quantity: i.quantity,
    unit_price: i.unitPrice,
    discount: i.discount,
  })),
  payments: s.payments.map((p) => ({
    method: p.method,
    amount: p.amount,
    reference: p.method === 'cash' ? null : p.reference,
  })),
})

const outcomeOf = (r: ServerResult): SyncOutcome => ({
  operationId: r.operation_id,
  saleId: r.sale_id,
  invoiceNumber: r.invoice_number,
  conflicts: r.conflicts,
  errorCode: r.error_code,
  errorMessage: r.error_message,
})

async function reschedule(rows: QueuedSale[], message: string, now = Date.now()) {
  await db.transaction('rw', db.queue, async () => {
    for (const r of rows) {
      const attempts = r.attempts + 1
      await db.queue.update(r.localId, {
        status: 'pending',
        attempts,
        nextAttemptAt: now + backoffMs(attempts),
        lastError: message,
      })
    }
  })
}

async function applyResults(rows: QueuedSale[], results: ServerResult[]): Promise<ServerResult[]> {
  const byId = new Map(results.map((r) => [r.client_operation_id, r]))
  await db.transaction('rw', db.queue, async () => {
    for (const row of rows) {
      const r = byId.get(row.localId)
      if (!r) {
        await db.queue.update(row.localId, {
          status: 'pending',
          lastError: 'No answer from the server',
        })
        continue
      }
      if (r.status === 'received') {
        // Another request is deciding it right now: look again shortly.
        await db.queue.update(row.localId, { status: 'pending', nextAttemptAt: Date.now() + 3_000 })
        continue
      }
      await db.queue.update(row.localId, {
        status: r.status as QueueStatus,
        outcome: outcomeOf(r),
        lastError: r.error_message,
      })
    }
  })
  return results
}

/** Sends rows to the server. Returns false if the attempt should stop for now (offline, signed out, ...). */
async function send(rows: QueuedSale[], deviceId: string, summary: DrainSummary): Promise<boolean> {
  try {
    const res = await api<{ results: ServerResult[] }>('/sync/sales', 'POST', {
      device_id: deviceId,
      operations: rows.map(payload),
    })
    summary.sent += rows.length
    for (const r of await applyResults(rows, res.results)) {
      if (r.status === 'applied') summary.applied++
      else if (r.status !== 'received') summary.held++
    }
    return true
  } catch (e) {
    if (!(e instanceof ApiError)) throw e
    if (e.status === 404) {
      await forgetDevice() // the server does not know this device: register it again next time
      await reschedule(rows, e.message)
      return false
    }
    if (e.status === 422 && rows.length > 1) {
      // One bad sale must not block the rest: send them one at a time to find it.
      for (const row of rows) if (!(await send([row], deviceId, summary))) return false
      return true
    }
    if (e.status === 422) {
      await db.queue.update(rows[0].localId, {
        status: 'failed',
        lastError: e.message,
        outcome: {
          operationId: null,
          saleId: null,
          invoiceNumber: null,
          conflicts: [],
          errorCode: 'invalid',
          errorMessage: e.message,
        },
      })
      summary.held++
      return true
    }
    // Offline, signed out, or a server problem: keep everything and try again later.
    await reschedule(rows, e.message)
    return false
  }
}

/** Held sales are decided by a manager on the server; learn what became of each. */
export async function refreshHeld(): Promise<number> {
  const held = await db.queue
    .where('status')
    .anyOf('conflict', 'failed')
    .filter((s) => !!s.outcome?.operationId)
    .toArray()
  let nowApplied = 0
  for (const row of held) {
    try {
      const op = await api<ServerResult & { id: string; invoice_number: string | null }>(
        `/sync/operations/${row.outcome!.operationId}`,
      )
      if (op.status === row.status && op.status !== 'applied') continue
      await db.queue.update(row.localId, {
        status: op.status as QueueStatus,
        outcome: { ...outcomeOf({ ...op, operation_id: op.id }) },
        lastError: op.error_message,
      })
      if (op.status === 'applied') nowApplied++
    } catch (e) {
      if (e instanceof ApiError && e.network) break
    }
  }
  return nowApplied
}

async function run(): Promise<DrainSummary> {
  const summary: DrainSummary = { sent: 0, applied: 0, held: 0, deferred: false }
  const { status } = useAuthStore.getState()
  if (status !== 'authed' || !useConnection.getState().online) return { ...summary, deferred: true }

  // A sale left "syncing" by a closed tab or a crash is simply sent again: the server is idempotent.
  await db.queue.where('status').equals('syncing').modify({ status: 'pending' })

  const meta = await getCatalogMeta()
  const batch = Math.min(meta?.settings.batchMax ?? DEFAULT_BATCH, DEFAULT_BATCH)
  let stopped = false
  let lastStore = meta?.storeId
  const tried = new Set<string>() // one run never sends the same sale twice, whatever the server says
  while (!stopped) {
    const due = (await db.queue.where('status').equals('pending').sortBy('soldAt')).filter(
      (r) => r.nextAttemptAt <= Date.now() && !tried.has(r.localId),
    )
    if (due.length === 0) break
    const store = due[0].storeId
    lastStore = store
    const rows = due.filter((r) => r.storeId === store).slice(0, batch)
    rows.forEach((r) => tried.add(r.localId))
    await db.queue
      .where('localId')
      .anyOf(rows.map((r) => r.localId))
      .modify({ status: 'syncing' })
    try {
      const deviceId = await ensureDevice(store)
      stopped = !(await send(rows, deviceId, summary))
    } catch (e) {
      await reschedule(rows, e instanceof Error ? e.message : 'Could not send')
      stopped = true
    }
  }
  if (summary.sent === 0 && !stopped) summary.deferred = true

  let booked = summary.applied
  if (useConnection.getState().online) booked += await refreshHeld()
  if (booked > 0 && lastStore) {
    try {
      await refreshCatalog(lastStore) // the stock moved on the server: take a fresh snapshot
    } catch {
      /* best effort; the next refresh will do it */
    }
  }
  await pruneSettled()
  return summary
}

let draining: Promise<DrainSummary> | null = null

/** Sends whatever is waiting. Several callers share one run. */
export function drainQueue(): Promise<DrainSummary> {
  draining ??= run().finally(() => {
    draining = null
  })
  return draining
}

/** Keeps trying: now, whenever the connection returns, when the tab is shown, and on a timer. */
export function startSyncLoop(intervalMs = 20_000): () => void {
  const tick = () => void drainQueue()
  tick()
  const timer = setInterval(tick, intervalMs)
  const unsubscribe = useConnection.subscribe((s, prev) => {
    if (s.online && !prev.online) tick()
  })
  const onVisible = () => document.visibilityState === 'visible' && tick()
  document.addEventListener('visibilitychange', onVisible)
  return () => {
    clearInterval(timer)
    unsubscribe()
    document.removeEventListener('visibilitychange', onVisible)
  }
}
