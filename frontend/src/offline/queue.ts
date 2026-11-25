import { db, getMeta, setMeta, type QueuedLine, type QueuedPayment, type QueuedSale } from './db'
import { deviceIdentifier } from './device'

export interface EnqueueInput {
  /** The idempotency key (the till's current sale key). Enqueueing twice stores it once. */
  operationId: string
  storeId: string
  cashierId: string
  cashierName: string
  customerId: string | null
  customerName: string | null
  soldAt: Date
  items: QueuedLine[]
  payments: QueuedPayment[]
  total: string
}

const COUNTER_KEY = 'receiptCounter'

/** e.g. OFF-A1B2-0007: the device's short code and its own running count. Provisional, not a tax invoice. */
export async function nextProvisionalNumber(): Promise<string> {
  const short = (await deviceIdentifier())
    .replace(/[^a-z0-9]/gi, '')
    .slice(0, 4)
    .toUpperCase()
  const n = ((await getMeta<number>(COUNTER_KEY)) ?? 0) + 1
  await setMeta(COUNTER_KEY, n)
  return `OFF-${short}-${String(n).padStart(4, '0')}`
}

/** Saves a sale on this device. Safe to call again for the same sale: it is stored once. */
export async function enqueueSale(input: EnqueueInput): Promise<QueuedSale> {
  return db.transaction('rw', db.queue, db.meta, async () => {
    const existing = await db.queue.get(input.operationId)
    if (existing) return existing
    const sale: QueuedSale = {
      localId: input.operationId,
      storeId: input.storeId,
      cashierId: input.cashierId,
      cashierName: input.cashierName,
      customerId: input.customerId,
      customerName: input.customerName,
      provisionalNumber: await nextProvisionalNumber(),
      soldAt: input.soldAt.toISOString(),
      items: input.items,
      payments: input.payments,
      total: input.total,
      status: 'pending',
      attempts: 0,
      nextAttemptAt: 0,
      lastError: null,
      outcome: null,
    }
    await db.queue.add(sale)
    return sale
  })
}

/** Stock the till still believes it has: the snapshot less everything sold here and not yet booked. */
export async function availableQuantity(variantId: string): Promise<number> {
  const variant = await db.variants.get(variantId)
  if (!variant) return 0
  const held = await db.queue
    .where('status')
    .anyOf('pending', 'syncing', 'conflict', 'failed')
    .toArray()
  const sold = held.reduce(
    (n, s) =>
      n + s.items.filter((i) => i.variantId === variantId).reduce((m, i) => m + i.quantity, 0),
    0,
  )
  return variant.quantity - sold
}

export const unsyncedCount = () => db.queue.where('status').anyOf('pending', 'syncing').count()

/** Forget old, fully settled sales so the queue does not grow forever. */
export async function pruneSettled(olderThanDays = 7, now = Date.now()) {
  const cutoff = now - olderThanDays * 86_400_000
  const old = await db.queue
    .where('status')
    .anyOf('applied', 'rejected')
    .filter((s) => new Date(s.soldAt).getTime() < cutoff)
    .primaryKeys()
  await db.queue.bulkDelete(old)
}
